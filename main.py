import os
import json
import random
import threading
from datetime import datetime, timedelta

import requests
import discord
from discord.ext import commands
from flask import Flask, request, jsonify

# ---------------- CONFIG ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "Bot_Data")
os.makedirs(DATA_DIR, exist_ok=True)

COIN_FILE = os.path.join(DATA_DIR, "users_coin_tx.json")
USED_HASH_FILE = os.path.join(DATA_DIR, "used_hashes.json")
CLAIM_META_FILE = os.path.join(DATA_DIR, "claim_meta.json")
DAILY_META_FILE = os.path.join(DATA_DIR, "daily_meta.json")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")  # token bot discord
LINKVERTISE_TOKEN = os.getenv("LINKVERTISE_TOKEN")  # api token linkvertise
FLASK_BASE = os.getenv("FLASK_BASE", "https://lonelytx.onrender.com")  # fallback nếu chưa set
LINKVERTISE_BASE = os.getenv("LINKVERTISE_BASE", "https://link-target.net/1236998/pgwULxnzsAkJ")
LINKVERTISE_VERIFY_URL = "https://publisher.linkvertise.com/api/v1/anti_bypassing"
FLASK_BASE = "https://lonelytx.onrender.com"

PREFIXES = ["!", "?", "/"]

PACKS = {
    "50": {"links": 1, "coin": 50},
    "100": {"links": 2, "coin": 100},
    "150": {"links": 3, "coin": 150},
}

CLAIM_COOLDOWN_HOURS = 1

# ---------------- JSON helpers ----------------
def load_json(path, default=None):
    if default is None:
        default = {}
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=4, ensure_ascii=False)
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# ---------------- Coin system ----------------
def get_balance(user_id):
    data = load_json(COIN_FILE, {})
    return int(data.get(str(user_id), {}).get("coin", 0))

def set_balance(user_id, amount):
    data = load_json(COIN_FILE, {})
    data[str(user_id)] = {"coin": int(amount)}
    save_json(COIN_FILE, data)

def add_balance(user_id, amount):
    bal = get_balance(user_id) + int(amount)
    set_balance(user_id, bal)
    return bal

def remove_balance(user_id, amount):
    bal = max(0, get_balance(user_id) - int(amount))
    set_balance(user_id, bal)
    return bal

# ---------------- Used-hash & cooldown ----------------
def is_hash_used(h):
    used = load_json(USED_HASH_FILE, {})
    return str(h) in used

def mark_hash_used(h, meta=None):
    used = load_json(USED_HASH_FILE, {})
    used[str(h)] = {
        "used_at": datetime.utcnow().isoformat(),
        "meta": meta or {}
    }
    save_json(USED_HASH_FILE, used)

def get_last_claim(user_id):
    meta = load_json(CLAIM_META_FILE, {})
    entry = meta.get(str(user_id))
    if not entry:
        return None
    try:
        return datetime.fromisoformat(entry.get("last_claim"))
    except Exception:
        return None

def update_last_claim(user_id):
    meta = load_json(CLAIM_META_FILE, {})
    meta[str(user_id)] = {"last_claim": datetime.utcnow().isoformat()}
    save_json(CLAIM_META_FILE, meta)

# ---------------- Discord Bot ----------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=PREFIXES, intents=intents)

def simple_embed(title, description, color=discord.Color.blurple()):
    e = discord.Embed(title=title, description=description, color=color, timestamp=datetime.utcnow())
    return e

@bot.event
async def on_ready():
    print(f"✅ Bot logged in as {bot.user} (id: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"📌 Slash commands synced: {len(synced)}")
    except Exception as e:
        print("Slash sync error:", e)

def is_admin_member(member: discord.Member):
    try:
        if member.guild is None:
            return False
        return member.guild.owner_id == member.id or member.guild_permissions.manage_guild
    except Exception:
        return False

# --------- Slash & Text Commands ----------
@bot.tree.command(name="coin", description="Xem số dư coin của bạn")
async def coin(interaction: discord.Interaction):
    bal = get_balance(interaction.user.id)
    e = simple_embed("💰 Số Dư", f"Bạn có {bal} coin", discord.Color.gold())
    e.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)

@bot.command(name="coin")
async def coin_text(ctx):
    bal = get_balance(ctx.author.id)
    e = simple_embed("💰 Số Dư", f"{ctx.author.mention}, bạn có {bal} coin", discord.Color.gold())
    await ctx.reply(embed=e, mention_author=False)

@bot.tree.command(name="addcoin", description="(Admin) Thêm coin cho user")
async def addcoin(interaction: discord.Interaction, user_id: str, amount: int):
    if not is_admin_member(interaction.user):
        await interaction.response.send_message(embed=simple_embed("❌ Lỗi", "Bạn không có quyền", discord.Color.red()), ephemeral=True)
        return
    new_bal = add_balance(user_id, amount)
    e = simple_embed("✅ Đã Thêm Coin", f"Đã cộng {amount} coin cho {user_id}\n💰 Số dư mới: {new_bal} coin", discord.Color.green())
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="removecoin", description="(Admin) Trừ coin của user")
async def removecoin(interaction: discord.Interaction, user_id: str, amount: int):
    if not is_admin_member(interaction.user):
        await interaction.response.send_message(embed=simple_embed("❌ Lỗi", "Bạn không có quyền", discord.Color.red()), ephemeral=True)
        return
    new_bal = remove_balance(user_id, amount)
    e = simple_embed("⚠️ Đã Trừ Coin", f"Đã trừ {amount} coin của {user_id}\n💰 Số dư mới: {new_bal} coin", discord.Color.orange())
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="setcoin", description="(Admin) Set coin cho user")
async def setcoin(interaction: discord.Interaction, user_id: str, amount: int):
    if not is_admin_member(interaction.user):
        await interaction.response.send_message(embed=simple_embed("❌ Lỗi", "Bạn không có quyền", discord.Color.red()), ephemeral=True)
        return
    set_balance(user_id, amount)
    e = simple_embed("🔧 Đã Cập Nhật Coin", f"Số dư của {user_id} = {amount} coin", discord.Color.blue())
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="taixiu", description="Chơi Tài Xỉu - chọn 'tai' hoặc 'xiu'")
async def taixiu(interaction: discord.Interaction, select: str, amount: int):
    user_id = str(interaction.user.id)
    bal = get_balance(user_id)
    if bal < amount:
        await interaction.response.send_message(embed=simple_embed("❌ Không đủ coin", f"Bạn chỉ có {bal} coin", discord.Color.red()), ephemeral=True)
        return
    dice = [random.randint(1, 6) for _ in range(3)]
    total = sum(dice)
    result = "tai" if 11 <= total <= 17 else "xiu"
    if select.lower() == result:
        add_balance(user_id, amount)
        outcome_text = f"🎉 Bạn thắng {amount} coin!"
        color = discord.Color.green()
    else:
        remove_balance(user_id, amount)
        outcome_text = f"💀 Bạn thua {amount} coin!"
        color = discord.Color.red()
    new_bal = get_balance(user_id)
    e = discord.Embed(title="🎲 Kết Quả Tài Xỉu", color=color)
    e.add_field(name="Xúc xắc", value=f"🎲 {dice[0]} • 🎲 {dice[1]} • 🎲 {dice[2]}", inline=False)
    e.add_field(name="Tổng", value=f"{total} → {result.upper()}", inline=False)
    e.add_field(name="Kết quả", value=outcome_text, inline=False)
    e.set_footer(text=f"Số dư: {new_bal} coin")
    e.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)

# ---------------- DAILY ----------------
def get_daily_meta(user_id):
    data = load_json(DAILY_META_FILE, {})
    return data.get(str(user_id))

def set_daily_meta(user_id, meta):
    data = load_json(DAILY_META_FILE, {})
    data[str(user_id)] = meta
    save_json(DAILY_META_FILE, data)

@bot.tree.command(name="daily", description="Điểm danh hàng ngày")
async def daily(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    now = datetime.utcnow()
    meta = get_daily_meta(user_id)
    streak = 1
    reward = 10
    if meta:
        last = datetime.fromisoformat(meta.get("last_claim"))
        streak = meta.get("streak", 0)
        if now < last + timedelta(hours=24):
            rem = (last + timedelta(hours=24)) - now
            await interaction.response.send_message(embed=simple_embed("⏳ Chưa thể điểm danh", f"Hãy quay lại sau {str(rem).split('.')[0]}", discord.Color.orange()), ephemeral=True)
            return
        if now <= last + timedelta(hours=48):
            streak += 1
        else:
            streak = 1
    reward = 10 if streak == 1 else 20 if streak == 2 else 30 if streak == 3 else 40 if streak == 4 else 50 if streak == 5 else 60 if streak == 6 else 70
    add_balance(user_id, reward)
    set_daily_meta(user_id, {"last_claim": now.isoformat(), "streak": streak})
    new_bal = get_balance(user_id)
    e = discord.Embed(title="📅 Điểm Danh Thành Công", description=f"Nhận **{reward} coin**!\n🔥 Chuỗi: {streak} ngày\n💰 Số dư: {new_bal} coin", color=discord.Color.green(), timestamp=now)
    e.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)

# ---------------- GETCOIN ----------------
from discord.ui import View, Button

@bot.tree.command(name="getcoin", description="Chọn gói coin muốn nhận")
async def getcoin(interaction: discord.Interaction):
    e = discord.Embed(
        title="💰 Nhận Coin Miễn Phí",
        description=(
            "Bạn có thể nhận coin bằng cách vượt qua Linkvertise.\n\n"
            "Giải thích:\n"
            "🔹 **1 link Linkvertise** = 1 lần xác thực.\n"
            "🔹 Bạn cần vượt **số link** tuỳ gói để nhận coin.\n\n"
            "**Các gói hiện có:**\n"
            "👉 Pack 50 xu = 2 linkvertise\n"
            "👉 Pack 100 xu = 3 linkvertise\n"
            "👉 Pack 150 xu = 4 linkvertise\n\n"
            "Bấm nút bên dưới để chọn gói bạn muốn claim ⬇️"
        ),
        color=discord.Color.gold(),
        timestamp=datetime.utcnow()
    )
    e.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)

    # Tạo view với 3 nút
    class PackView(View):
        def __init__(self):
            super().__init__(timeout=60)  # 1 phút
        @discord.ui.button(label="50 Coins", style=discord.ButtonStyle.green)
        async def pack50(self, interaction_btn: discord.Interaction, button: Button):
            await send_pack_link(interaction_btn, "50")
        @discord.ui.button(label="100 Coins", style=discord.ButtonStyle.blurple)
        async def pack100(self, interaction_btn: discord.Interaction, button: Button):
            await send_pack_link(interaction_btn, "100")
        @discord.ui.button(label="150 Coins", style=discord.ButtonStyle.red)
        async def pack150(self, interaction_btn: discord.Interaction, button: Button):
            await send_pack_link(interaction_btn, "150")

    await interaction.response.send_message(embed=e, view=PackView(), ephemeral=True)

# Hàm gửi link khi chọn pack
async def send_pack_link(interaction: discord.Interaction, pack: str):
    link = f"{LINKVERTISE_BASE}?user_id={interaction.user.id}&pack={pack}"
    e = discord.Embed(
        title=f"🔗 Nhận Coin Pack {pack}",
        description=(
            f"Bạn đã chọn **Pack {pack}** 🎉\n"
            f"👉 [Click vào đây để vượt Linkvertise]({link})\n\n"
            f"Sau khi vượt xong, hệ thống sẽ tự động cộng **{PACKS[pack]['coin']} coin** "
            f"vào tài khoản của bạn."
        ),
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    e.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e, ephemeral=True)
# ---------------- Flask Claim Endpoint ----------------
app = Flask(__name__)

@app.route("/claim", methods=["POST"])
def claim():
    body = request.get_json() or {}
    user_id = str(body.get("user_id", "")).strip()
    pack = str(body.get("pack", "")).strip()
    hash_value = str(body.get("hash", "")).strip()
    if not user_id or pack not in PACKS or not hash_value:
        return jsonify({"error": "Missing params"}), 400
    last = get_last_claim(user_id)
    if last and datetime.utcnow() < last + timedelta(hours=CLAIM_COOLDOWN_HOURS):
        return jsonify({"error": "Cooldown"}), 429
    if is_hash_used(hash_value):
        return jsonify({"error": "Hash used"}), 400
    try:
        params = {"token": LINKVERTISE_TOKEN, "hash": hash_value}
        resp = requests.get(LINKVERTISE_VERIFY_URL, params=params, timeout=8)
        rj = resp.json()
    except Exception as e:
        return jsonify({"error": "Verify fail", "detail": str(e)}), 502
    verified = False
    if isinstance(rj, dict):
        if rj.get("success") is True or rj.get("data") or rj:
            verified = True
    if not verified:
        return jsonify({"error": "Xác thực thất bại"}), 400
    mark_hash_used(hash_value, meta={"user": user_id, "pack": pack})
    reward = PACKS[pack]["coin"]
    new_bal = add_balance(user_id, reward)
    update_last_claim(user_id)
    async def notify(uid, reward, balance):
        try:
            user = await bot.fetch_user(int(uid))
            embed = discord.Embed(title="🎉 Claim Thành Công", description=f"Bạn nhận được **{reward} coin**!\n💰 Số dư: {balance} coin", color=discord.Color.green(), timestamp=datetime.utcnow())
            embed.set_author(name=str(user), icon_url=user.display_avatar.url)
            await user.send(embed=embed)
        except Exception as e:
            print("DM error:", e)
    bot.loop.create_task(notify(user_id, reward, new_bal))
    return jsonify({"message": f"✅ Nhận {reward} coin", "new_balance": new_bal}), 200

def run_flask():
    app.run(host="0.0.0.0", port=5000)

# ---------------- Run ----------------
if __name__ == "__main__":
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    bot.run(DISCORD_TOKEN)
