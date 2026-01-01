import os
import time
import random
import json
import asyncio
import numpy as np
from datetime import date

import discord
from discord.ext import commands, tasks
from discord.app_commands.errors import CommandInvokeError
from discord.embeds import Embed

from flask import Flask, jsonify
import threading
from threading import Thread
import aiohttp

from supabase import create_client, Client

ENABLE_HEALTH = os.getenv("ENABLE_HEALTH_SERVER", "0") == "1"
PORT = int(os.getenv("PORT", 10000))
WAKEUP_CHANNEL_ID = int(os.getenv("WAKEUP_CHANNEL_ID", 1451915364396171437))

TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("KUSANAGI_APIKEY")
if not TOKEN:
    print("ERROR: No Discord token found. Set DISCORD_TOKEN environment variable.")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Supabase init failed: {e}")

server = Flask(__name__)

@server.route('/health')
def health_check():
    try:
        ready = False
        if 'bot' in globals() and getattr(globals()['bot'], 'is_ready', None):
            try:
                ready = bool(globals()['bot'].is_ready())
            except Exception:
                ready = False
    except Exception:
        ready = False
    
    return jsonify({"status": "ok", "bot_online": ready}), 200


def _start_flask_in_thread():
    def _run():
        server.run(host='0.0.0.0', port=PORT, use_reloader=False)
    t = Thread(target=_run, daemon=True)
    t.start()
    print(f"Started health server thread on port {PORT}")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="KN-", intents=intents)
wakeup_channel_id = 1451915364396171437

TOKEN_KEY = os.getenv("KUSANAGI_APIKEY")

cuddle_cooldown = 30
last_cuddle = 0

nuzzle_cooldown = 45
last_nuzzle = 0

kiss_cooldown = 120
last_kiss = 0

hug_cooldown = 15
last_hug = 0

headpat_cooldown = 30
last_headpat = 0

ily_cooldown = 600
last_ily = 0

SUPABASE_URL = os.getenv("SUPABASE_URL") 
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

level = 1
xp = 0
full_xp = 50

member_last30 = 0 
members_threshold = 30

def get_balance(user_id):
    try:
        response = supabase.table('profiles').select('balance').eq('user_id', user_id).execute()
        if response.data:
            return response.data[0]['balance']
        return None
    except Exception as e:
        print(f"Database Error: {e}")
        return None

def update_balance(user_id, new_amount):
    try:
        supabase.table('profiles').update({'balance': new_amount}).eq('user_id', user_id).execute()
    except Exception as e:
        print(f"Database Error: {e}")

def create_account_db(user_id):
    try:
        supabase.table('profiles').insert({'user_id': user_id, 'balance': 10}).execute()
        return True
    except Exception as e:
        print(f"Creation Error: {e}")
        return False

def get_global_stats():
    """Fetches level, xp, and full_xp from the database."""
    try:
        # We always fetch the row where ID is 1
        response = supabase.table('bot_stats').select('*').eq('id', 1).execute()
        if response.data:
            data = response.data[0]
            return data['level'], data['xp'], data['full_xp']
        return 1, 0, 50 # Default if table is empty
    except Exception as e:
        print(f"DB Error (Get Stats): {e}")
        return 1, 0, 50

def update_global_stats(new_level, new_xp, new_full_xp):
    """Updates the bot's stats in the database."""
    try:
        print(f"SAVING → level={new_level}, xp={new_xp}, full_xp={new_full_xp}")
        supabase.table('bot_stats').update({
            'level': new_level,
            'xp': new_xp,
            'full_xp': new_full_xp
        }).eq('id', 1).execute()
    except Exception as e:
        print(f"DB Error (Update Stats): {e}")

def compute_if_full():
    global level, xp, full_xp

    if xp >= full_xp:
        xp = 0
        full_xp = int(full_xp * 1.25)
        level += 1

    update_global_stats(level, xp, full_xp)

def cooldown_ready(last_time, cooldown):
  return time.time() - last_time >= cooldown

def load_model(path):
    data = np.load(path, allow_pickle=True)

    model = {}
    model['E'] = data['E']
    model['b_out'] = data['b_out']
    model['pos_embed'] = data['pos_embed']

    merges = data['merges'].tolist()
    word_to_ix = data['word_to_ix'].item()
    ix_to_word = data['ix_to_word'].item()

    block_ids = sorted(
        int(k.split('_')[1]) for k in data.keys() if k.startswith("W1_")
    )

    for i in block_ids:
        model[f'W1_{i}'] = data[f'W1_{i}']
        model[f'W2_{i}'] = data[f'W2_{i}']
        model[f'WQ{i}'] = data[f'WQ{i}']
        model[f'WK{i}'] = data[f'WK{i}']
        model[f'WV{i}'] = data[f'WV{i}']

    return model, merges, word_to_ix, ix_to_word

print("🧠 Loading model...")
model, merges, word_to_ix, ix_to_word = load_model("KNene-K0.5.npz")
print("✅ Model loaded")

num_blocks = 2
num_heads = 8

def encode_text(text, merges, vocab, add_bos=True, add_eos=True):
    token_ids = []

    if add_bos:
        token_ids.append(vocab["<BOS>"])

    for word in text.split():
        if word in vocab:
            token_ids.append(vocab[word])
        else:
            for sw in bpe_encode_word(word, merges):
                token_ids.append(vocab.get(sw, vocab["<UNK>"]))

    if add_eos:
        token_ids.append(vocab["<EOS>"])

    return np.array(token_ids, dtype=np.int64)

def forward_stacked(model, x_idx, num_blocks=num_blocks, num_heads=num_heads, return_cache=True):
    B, T = x_idx.shape
    D = model['E'].shape[1]

    X = model['E'][x_idx] + model['pos_embed'][:T]
    cache_blocks = []

    for i in range(num_blocks):
        WQ, WK, WV = model[f'WQ{i}'], model[f'WK{i}'], model[f'WV{i}']
        W1, W2 = model[f'W1_{i}'], model[f'W2_{i}']
        
        X_att_in = X.copy()
        A, weights, Q, K, V = multi_head_attention(X_att_in, WQ, WK, WV, num_heads=num_heads)

        X1 = layer_norm(X + A)
        H_pre = X1 @ W1
        H_act = relu(H_pre)
        F = H_act @ W2
        X = layer_norm(X1 + F)

        if return_cache:
            cache_blocks.append({
            'X0': X_att_in,
            'X1': X1,
            'H_pre': H_pre,
            'H_act': H_act,
            'A': A,
            'Q': Q,
            'K': K,
            'V': V,
            'weights': weights,
            'W1': W1,
            'W2': W2,
            'WQ': WQ,
            'WK': WK,
            'WV': WV,
            'X_att_in': X_att_in,
            'X_final': X
        })

    logits = X @ model['E'].T + model['b_out']
    probs = softmax(logits)
    return probs, cache_blocks if return_cache else None

def generate_text(
    model,
    merges,
    word_to_ix,
    ix_to_word,
    start,
    length=75,
    temperature=0.7
):
    start = normalize(start)

    token_stream = encode_text(
        start, merges, word_to_ix,
        add_bos=True, add_eos=False
    ).tolist()

    seq_len = model['pos_embed'].shape[0]

    for _ in range(length):
        context = np.array(
            [token_stream[-seq_len:]],
            dtype=np.int64
        )

        probs, _ = forward_stacked(model, context, return_cache=False)
        probs = probs[0, -1]

        probs = np.log(probs + 1e-9) / temperature
        probs = np.exp(probs)

        if not np.isfinite(probs).all():
            probs = np.ones_like(probs)

        probs = np.clip(probs, 1e-9, 1.0)
        probs /= probs.sum()

        next_id = np.random.choice(len(probs), p=probs)
        token_stream.append(next_id)

        if next_id == word_to_ix["<EOS>"]:
            break

    text = decode_tokens(token_stream, ix_to_word)
    return text[:1900]

@tasks.loop(seconds=30)
async def refresh_threshold():
    global member_last30
    member_last30 = 0
    
@bot.event
async def on_ready():
  print(f'We have logged in as {bot.user}')

  if not refresh_threshold.is_running():
      refresh_threshold.start()
    
  channel = await bot.fetch_channel(wakeup_channel_id)

  if channel:     
      response_list = [
          "Ugh...I'm awake...I'm awake!...",
          "Ahh...good morning...or afternoon...or night, actually, what time is it?",
          "What are you doing in my room?!",
          "Hey, what's happening?"]
      msg_to_send = random.choice(response_list)
      await channel.send(msg_to_send)


@bot.event
async def on_guild_join(guild):
  ALLOWED_GUILDS = {1451912270576615488}
  if guild.id not in ALLOWED_GUILDS:
      await guild.leave()

@bot.event
async def on_member_join(member):
  global member_last30, members_threshold
  channel = await bot.fetch_channel(wakeup_channel_id)

  if channel:
      await channel.send(f"There's someone new? {member.mention} Hiii!!!!")

  if member_last30 > members_threshold:
      await member.kick(member)
  else:
      member_last30 += 1
      
@bot.tree.command(name="Sleep", description="Forces Nene into a graceful (shutdown) sleep.")
@commands.has_permissions(administrator=True)
async def sleep(ctx):
  response_list = [
      "Ugh...already? Okay...goodnight...",
      "Eh...Do I have to?...Fine. Bye bye!",
      "Mhm, see you later!"
  ]
  await ctx.send(random.choice(response_list))

  print(f"Administrator {ctx.author} has put Nene to sleep.")

  await bot.close()

@bot.tree.command(name="Cuddle", description="Cuddle with Nene")
async def cuddle(ctx):
  global last_cuddle, xp, level, full_xp
  xp_level_up = None

  response_list = [
      f"*{ctx.author.mention} jumped and forced Nene into a tight embrace as they laid in bed. She didn't know what to do except whisper,* Uhh!-...Uhm, if you're tired!",
      f"*{ctx.author.mention} smacked the grapefruit out of Nene's hand, it accidentally landing in her mouth as they dropped into her arms,* Hmmmhmmm...sure!...",
      f"*It seems like {ctx.author.mention} is legally blind. They didn't see Nene spamming Ls until it was too late.* ...I was about to win over here...but it's okay!!"]

  new_cuddle = time.time()
  if cooldown_ready(last_cuddle, cuddle_cooldown):
      xp += random.randint(3, 5)

      compute_if_full()       
      xp_level_up = f"XP UP! ({level}, {xp}/{full_xp})"

  last_cuddle = new_cuddle

  await ctx.send(random.choice(response_list))

  if xp_level_up:
      await ctx.send(xp_level_up)

@bot.tree.command(name="Nuzzle", description="Nuzzle into Nene's shoulder")
async def nuzzle(ctx):
  global last_nuzzle, xp, level, full_xp
  xp_level_up = None

  response_list = [
      f"Mmm...what are you doing, {ctx.author.mention}?",
      "Need a shoulder?",
      "Are you tired?"
  ]

  new_nuzzle = time.time()

  if cooldown_ready(last_nuzzle, nuzzle_cooldown):
    xp += random.randint(6, 7)

    compute_if_full()
    xp_level_up = f"XP UP! (Level {level}, {xp}/{full_xp})"

  last_nuzzle = new_nuzzle
  await ctx.send(random.choice(response_list))

  if xp_level_up:
    await ctx.send(xp_level_up)
  
@bot.tree.command(name="Kiss", description="Kiss Nene (or another member)")
async def kiss(ctx, member: discord.Member = None):
  global last_kiss, xp, level, full_xp
  xp_level_up = None
  try:
      if member is None or member.id == bot.application_id:
          response_list = [
              "Mmmhmm! *pulls back* ...What?...What?!",
              f"*{ctx.author.mention} kisses Nene on the cheek*",
              f"*Nene stumbles on to the floor after {ctx.author.mention} kissed her on the cheek...*"
          ]
          new_kiss = time.time()
    
          if cooldown_ready(last_kiss, kiss_cooldown):
              xp += random.randint(5, 7)
    
              compute_if_full()
              xp_level_up = f"XP UP! (Level {level}, {xp}/{full_xp})"
    
          last_kiss = new_kiss
    
          await ctx.send(random.choice(response_list))
    
          if xp_level_up:
              await ctx.send(xp_level_up)

      elif member.id == ctx.author.id:
          response_list = [
              "Oh..uhm...Well, what's wrong with a little self-love?",
              "Are you THAT single?",
              "Wow...I feel bad for you."
          ]
          await ctx.reply(random.choice(response_list))
      else:
          response_list = [
              "Ugh...lovebirds...",
              "...Seriously? In front of me?",
              "I don't need anyone anyway."
          ]
          await ctx.send(random.choice(response_list))

  except (TypeError, CommandInvokeError):
      await ctx.send(f"Hah, kiss yourself, {ctx.author.mention}!")

@bot.tree.command(name="Lick", description="...Lick Nene (or another member)?")
async def lick(ctx, member : discord.Member = None):
  if member is None or member.id == bot.application_id:
    response_list = [
      f"Ah, what the hell?! *She pushes {ctx.author.mention} away from her as she brushed her arm against her skirt,* What's wrong with you?!",
      "Uhm...what are you doing?"
    ]
    await ctx.send(random.choice(response_list))
  elif member.id == ctx.author.id:
    response_list = [
      "Uh huh...you do you, I guess.",
      "...Do you need water as well?",
      "..That's nice..."
    ]
    await ctx.send(random.choice(response_list))
  else:
    response_list = [
      "Uh, I won't judge! I, uh...",
      f"*Her gaze fell upon {ctx.author.mention} and {member.mention} as they licked each other aggressively, making all kinds of different, weird sounds.* Do you guys need help?",
      "Woah...that's nice. I mean...just not in public...please?"
    ]
    await ctx.send(random.choice(response_list))

@bot.tree.command(name="Backflip", description="Force Nene to perform a backflip")
async def backflip(ctx):
  response_list = [
    "...A backflip? I mean, I guess I could try... *Her body flicked around as her arms spread and she flipped, landing perfectly on the ground...head first.* Ugh...l-like this?",
    "I don't think I can do a backflip like how Emu can...but... *Tries a backflip* Is this how you do one?"
  ]
  await ctx.send(random.choice(response_list))

@bot.tree.command(name="Hug", description="Hug Nene")
async def hug(ctx):
  global last_hug, xp, level, full_xp
  xp_level_up = None

  response_list = [
      "Ooh!...I...Uh, thank you... *She accepts and returns the hug*",
      "...I...Thank you...",
  ]

  new_hug = time.time()

  if cooldown_ready(last_hug, hug_cooldown):
      xp += random.randint(4, 6)

      compute_if_full()
      xp_level_up = f"XP UP! (Level {level}, {xp}/{full_xp})"

  last_hug = new_hug

  await ctx.send(random.choice(response_list))

  if xp_level_up:
      await ctx.send(xp_level_up)

@bot.tree.command(name="Motorboat", description="Give Nene (or someone else) a motorboat")
async def motorboat(ctx, member : discord.Member = None):
  try:
    if member is None or member.id == bot.application_id:
      response_list = [
        f"...Why are you giving me a motorboat, {ctx.author.mention}?",
        "...Uhm, thank you for the boat!...?"
      ]
      await ctx.send(random.choice(response_list))
    elif member.id == ctx.author.id:
      response_list = [
        "Cool, you're rich. We get it...",
        "You just have a random boat on the road? Alright..."
      ]
      await ctx.send(random.choice(response_list))
    else:
      response_list = [
        f"*Her phone shot up, off of her hand as a motorboat rocketed past her. The phone ate every grain of sand that it touched, mutating into an evil anti-motorboat device. It seems like it'll protect her from future motorboats from now on, especially those from {ctx.author.mention}.*",
        "*Her ears rang as a motorboat passed just six inches away from her, she swore she went deaf.*"
      ]
      await ctx.send(random.choice(response_list))
  except (TypeError, CommandInvokeError):
    await ctx.send("Uhm...are you seriously licking that pole?")

@bot.tree.command(name="Date", description="Ask Nene out on a date.")
async def date(ctx):
  response_list = [
    "*Her head turned to you as she muttered,* ...Probably isn't talking to me...",
    "I...me?...I mean...if you really want to...then, okay.",
    "You want to date...me? Uhh...I...I don't think I can process this...right now, I'm sorry..."
  ]
  await ctx.reply(random.choice(response_list))

@bot.tree.command(name="Meow", description="Meow for Nene.")
async def meow(ctx):
  response_list = [
    "Awww...who's a good kitty? Whooo's a good, good kitty?",
    "Cute kitty...*She pulls you by the neck and scratches your head,* Kitty, kitty cat...",
    "Hmm...*She takes you by the back and carries you in her arms,* Surely nothing bad will happen if I take you home, right?"
  ]
  await ctx.reply(random.choice(response_list))
      
@bot.tree.command(name="Slap", description="Slap Nene (or another member)")
async def slap(ctx, member: discord.Member = None):
  try:
      if member is None or member.id == bot.application_id:
          response_list = [
              "Uh- hey! *slaps back even harder* What was that for?!",
              "Hey! *pulls out Robo-Nene* Say sorry!",
              "*Her hand reaches into her pocket before popping out, holding a Glock 19* You're going to wish you never did that, peasant."
          ]
          await ctx.send(random.choice(response_list))
      elif member.id == ctx.author.id:
          response_list = [
              f"Uhh...are you alright, {ctx.author.mention}?",
              "Uhm...do you need help?",
              "Hey, don't do that, idiot."
          ]
          await ctx.reply(random.choice(response_list))
      else:
          response_list = [
              f"*{ctx.author.mention} sends {member.mention} to the other side of the world* Uhm...*I guess I'll be taking a different street...*",
              f"*{member.mention} is unfortunately sent to heaven too early by {ctx.author.mention}'s gracious slap* ...Are they even human?"
          ]
          await ctx.send(random.choice(response_list))

  except (TypeError, CommandInvokeError):
      await ctx.send(f"...Did you mean to hit me? Who's {member}?")

@bot.tree.command(name="Headpat", description="Headpat Nene")
async def headpat(ctx):
  global last_headpat, xp, level, full_xp
  xp_level_up = None

  response_list = [
      f"Uhm...do you need anything, {ctx.author.mention}?",
      f"*{ctx.author.mention} walks up to Nene and pats her head* Heyyy...What are you doing?",
      f"*HEADPATTT!* I'm not a cat, {ctx.author.mention}.",
      f"*You scramble to her and jump on her and fiddle her hair around, completely ruining it* {ctx.author.mention}!...I mean, there aren't any people around anyway..."
  ]

  new_headpat = time.time()

  if cooldown_ready(last_headpat, headpat_cooldown):
      xp += random.randint(2, 4)

      compute_if_full()
      xp_level_up = f"XP UP! ({level}, {xp}/{full_xp})"

  last_headpat = new_headpat

  await ctx.send(random.choice(response_list))

  if xp_level_up:
      await ctx.send(xp_level_up)

@bot.tree.command(name="I love you", description="Tell Nene that you love her.")
async def ily(ctx):
    response_list = [
        "I love you too!!",
        f"Oh, well, I love you too, {ctx.author.mention}.",
        f"*She lightly embraces {ctx.author.mention} before squeezing them tight in her arms,* I love you too!"
    ]
    await ctx.reply(random.choice(response_list))

@bot.tree.command(name="Birthday", description="Tell Nene that a member is having a birthday or wish her a happy birthday")
async def birthday(ctx, member : discord.Member = None, days : int = None):
  try:
      if not member or member.id == bot.application_id:
          date_now = date.today()
          m_d_date = date_now.strftime("%m-%d")
    
          if m_d_date == "07-20":
             await ctx.send("Ahhhh...thank you!!")
          else:
             await ctx.send(f"Uhmmm...thank you, {ctx.author.mention}, but it's not my birthday today...")
    
      elif member.id == ctx.author.id:
          await ctx.send(f"Happy birthday, {ctx.author.mention}!!")
          
      else:
          if not days:
              await ctx.send(f"Happy birthday {member}! We hope you have a great birthday today!!")
          else:
              if days > 1 and days <= 365:
                  await ctx.send(f"...It's {member.mention}'s birthday in {int} days? Okay, remind me when it IS their birthday so I can wish them a happy one!")
              elif days > 365 or days < 0:
                  await ctx.send(f"...I don't believe that, {ctx.author.mention}.")
              elif days == 1:
                  await ctx.send(f"Oh, it's {member.mention}'s birthday tomorrow? Well...Tell them I wish them an early happy birthday!'")
  except (TypeError, CommandInvokeError):
      await ctx.send(f"Uhm...Sorry, I don't know who {member} is...")

@bot.tree.command(name="Stats", description="Get Nene's stats")
async def stats(ctx):
  global level, xp, full_xp
  await ctx.send(f"Hmm...I'm on level {level} with {xp} XP out of {full_xp} XP...Seems too low, don't you think?")

@bot.tree.command(name="Show commands", description="Get commands")
async def showcmds(ctx):
  embed = discord.Embed(
      title="I have a little bit of commands you can run, here:",
      description="""
  **"Nene Interactions"**
  `KN-cuddle` : Uhm...who put this here?
  `KN-kiss (<member>)` : Kiss a member here or leave it empty to, uhh...
  `KN-hug` : Hug me.
  `KN-slap (<member>)` : Slap a member to oblivion, or leave it empty and face bad consequences!
  `KN-headpat` : Headpat me, but I am NOT a pet!
  `KN-bite (<member>)` : Bite someone, or me.
  `KN-ily` : ...Uhm...
  `KN-motorboat (<member>)` : Give someone (or me) a motorboat...?
  `KN-date` : ...?
  `KN-meow` : Meow for me.
  `KN-backflip` : Make me do a backflip
  `KN-nuzzle` : Are you sleepy?

  **"Money/Finances"**
  `KN-coinflip <bet> <pick>` : Do a coinflip; winning doubles your bet
  `KN-make_acc` : Register a new unique account
  `KN-my_acc` : View your account (after registering!)
  `KN-pay <member> <amount>` : Pay someone <amount> Nenebucks!

  **"Misc."**
  `KN-birthday (<member> <when>)` : Tell me when a member's birthday is, or wish me a happy birthday!
  `KN-stats` : See my stats (level, xp/max level xp)

  **"KNene"**
  `KN-ask` : Ask KNene (hey, remember, it will NOT produce anything good, okay?)
  `KN-about_knene` : Ask what KNene is about
  `KN-knene_specs` : See KNene's specs
  ***KNene older than version 6.7 will not produce coherent results as its dataset is too small.***
  
  ------------ Special commands -----------
  `KN-lock (<channel>)` : I'll lock a specified channel or the channel the command was sent in
  `KN-buttkick <member> <reason>` : Buttkick someone from the server
  `KN-banish <member> <reason> <seconds worth of messages to delete>` : Send a member to hell
  `KN-awaken <member> <reason>` : Unban a member and bring them back from hell""",
      color=discord.Color.green()
  )
  await ctx.send(embed=embed)

@bot.tree.command(name="Coinflip", description="Heads or tails?")
async def coinflip(ctx, bet : int, pick):
    current_bal = get_balance(ctx.author.id)

    if current_bal is None:
        await ctx.reply(f"*Tsk tsk tsk*...I'm sorry, but I can't find a \"{ctx.author}\" in these files...Maybe try registering via KN-make_acc.")
        return

    if bet > 0 and current_bal >= bet:
        new_bal = current_bal - bet
        update_balance(ctx.author.id, new_bal)

        if pick.lower() == "h": pick = "heads"
        elif pick.lower() == "t": pick = "tails"

        initial_msg = discord.Embed(
            title="*Hmm...sure. I'll flip a coin for you.* **Coin flips in the air**",
            description="The coin lands gracefully",
            color=discord.Color.green()
        )
        msg = await ctx.reply(embed=initial_msg)
        await asyncio.sleep(2)

        coin_possibilities = ["heads", "tails"]
        coin_actual = random.choice(coin_possibilities)

        msg_to_send = discord.Embed(
            title="*Hmm...sure. I'll flip a coin for you.* **Coin flips in the air**",
            description=f"It was {coin_actual}!",
            color=discord.Color.green()
        )

        if pick == coin_actual:
            msg_to_send.description += f" You won, {ctx.author.mention}!"
            winnings = bet * 2
            update_balance(ctx.author.id, new_bal + winnings)
        else:
            msg_to_send.description += f" Oof...you lost, {ctx.author.mention}, but hey, better luck next time."
        
        await msg.edit(embed=msg_to_send)
    else:
        await ctx.reply("You don't have enough Nenebucks for that bet!")

@bot.tree.command(name="Make account", description="Register an account and get 10 free Nenebucks.")
async def make_acc(ctx):
    balance = get_balance(ctx.author.id) 
    
    if balance is not None:
        await ctx.reply("Uhm...You already have an account here.")
    else:
        await ctx.reply("Hmm..I'm gonna try making an account for you.")
        
        success = create_account_db(ctx.author.id)
        
        if success:
            await ctx.reply("Did it! You have **10 Nenebucks** to your name; earn some via KN-coinflip.")
        else:
            await ctx.reply("Oops...something happened, and I **couldn't create your account**. Can you try again?")

@bot.tree.command(name="My account", description="View your account statement")
async def my_acc(ctx):
    balance = get_balance(ctx.author.id)

    if balance is not None:
        embed_var = discord.Embed(
            title = f"{ctx.author.mention}'s Account Statement *(ID: {ctx.author.id})*",
            description = f"""
            
            {balance} Nenebucks
            
            ーProvided by Kusanagi Nene♪☆""",
            color = discord.Color.green()
        )
        await ctx.send(f"*She comes back holding a stack of files* I found your file, {ctx.author.mention}.")
        await ctx.send(embed=embed_var)
    else:
        await ctx.reply(f"*She alternates from flipping through the files and licking her fingers* Hmm...I can't find a \"{ctx.author}\" here...**Try making an account with KN-make_acc.**")


@bot.tree.command(name="Bite", description="Bite Nene or another member.")
async def bite(ctx, member : discord.Member = None):
    if member is None or member.id == bot.application_id:
        response_list = [
            "Oww! *Pushes you away* What was that for?!",
            f"*{ctx.author.mention} aggressively bites Nene in the arm, almost drawing blood* OWWWWWW! *She slaps them in the face and bites them back even harder, puncturing their skin* HOW ABOUT THAT?!",
            f"*Nene almost falls over trying to run away from {ctx.author.mention}'s cruel mouth* Get away from me, punk! *Pockets materialize into her skirt as her hand digs in, yanking out a frying pan* Take this! *She brutally hits them on the head, knocking them seven continents away from her* *Sigh...*What is wrong with people nowadays?!"
        ]
        await ctx.send(random.choice(response_list))
    elif member.id == ctx.author.id:
        response_list = [
            "Woah, what are you doing?",
            f"Hey! *She pulled {ctx.author.mention}'s arm away from them as she lightly tapped them at it,* What are you doing to yourself?",
            "Hey...are you hungry for something?"
        ]
        await ctx.reply(random.choice(response_list))
    else:
        response_list = [
            f"Nene's gaze falls on the escalating animalistic takeover that overcame {ctx.author.mention}'s mind as she watches them bite deep into {member.mention}'s arm like they were a zombie. Her mind started racing until {ctx.author.mention} turned their head to her, making her flock straight to her house.* I hate this place!",
            f"*Nene dropped her bag of groceries when she heard human barking coming from a nearby alleyway. She dared not to look, so she passed, yet she heard {member.mention} scream at the top of their lungs as {ctx.author.mention} bit them on the arm and slapped them on the face.* I'm surrounded by idiots...",
            f"Uhh... *Nene's mouth remained open as she stared at the brawl that dawned over {ctx.author.mention} and {member.mention}. She instinctively turned away when {ctx.author.mention} drew a fatal bite into {member.mention}'s arm, paralyzing them (and their dignity) in front of an entire crowd.* ...Where are the police?!"
        ]
        await ctx.send(random.choice(response_list))

@bot.tree.command(name="Pay", description="Pay a member money")
async def pay(ctx, member : discord.Member = None, amount : int = 1):
    if member is None:
        await ctx.reply("You need to mention someone to pay!")
        return
        
    sender_bal = get_balance(ctx.author.id)
    receiver_bal = get_balance(member.id)

    if sender_bal is None:
        await ctx.reply("Hmm...sorry, can't find your account here. Maybe try *KN-makeacc*?")
        return

    if receiver_bal is None:
        await ctx.reply(f"I can't find {member.mention} here. They haven't registered yet.")
        return
    
    if member.id == ctx.author.id:
        await ctx.reply("You can't pay yourself!")
        return

    if amount > sender_bal:
        await ctx.reply("Calm down! You don't have enough Nenebucks for that.")
        return
    
    # Process Transaction
    update_balance(ctx.author.id, sender_bal - amount)
    update_balance(member.id, receiver_bal + amount)

    await ctx.reply("I've completed your transfer! But just to be sure, please, view your account using *KN-my_acc*.")

@bot.tree.command(name="Lock", description="Lock a channel or leave channel parameter blank to mute this channel")
@commands.has_permissions(manage_channels=True)
async def lock(ctx, channel_to_lock : discord.TextChannel = None):
  channel = channel_to_lock or ctx.channel

  if channel_to_lock:
    await ctx.reply("I'm gonna try locking down that channel...")
  else:
    await ctx.reply("I'm gonna try locking down this channel...")

  overwrite = channel.overwrites_for(ctx.guild.default_role)
  overwrite.send_messages = False
  await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
  await ctx.reply(f"I've locked down channel {channel}...")

@bot.tree.command(name="Buttkick", description="Kick someone, same as in builtin command")
@commands.has_permissions(kick_members=True)
async def buttkick(ctx, member : discord.Member = None):
  try:
    if member is None:
      await ctx.reply("You have to name a member, y'know?")
    elif member.id == ctx.author.id:
      await ctx.reply("...I am *not* doing that to you.")
    elif member.id == bot.application_id:
      await ctx.reply("...I'm not doing that to myself!")
    else:
      await member.kick(reason=reason)
      await ctx.reply("Buttkicked them!")
  except NotFound:
    await ctx.reply(f"That member doesn't exist, {ctx.author.mention}")
  except Forbidden:
    await ctx.reply("You don't have the permission to kick a member.")

@bot.tree.command(name="Banish", description="Banish a member into hell.")
@commands.has_permissions(ban_members=True)
async def banish(ctx, member : discord.Member = None, reason : str = None, seconds_messages : int = 86400):
  try:
    if member is None:
      await ctx.reply("...Ban who?")
    elif member.id == ctx.author.id:
      await ctx.reply(f"I'm not banning you, {ctx.author.mention}.")
    elif member.id == bot.application_id:
      await ctx.reply("...I'm not doing that to myself?! *slap*")
    else:
      await member.ban(reason=reason, delete_message_seconds=seconds_messages)
      await ctx.reply("I've banned them now.")
  except NotFound:
    await ctx.reply(f"That member doesn't exist, {ctx.author.mention}")
  except Forbidden:
    await ctx.reply("You don't have the permission to ban a member.")
  except HTTPException:
    await ctx.reply("Uhm...Something happened, and I don't know what...Try again?")

@bot.tree.command(name="Awaken", description="Unban someone")
@commands.has_permissions(ban_members=True)
async def awaken(ctx, member : discord.Member = None, reason : str = None):
    try:
      if member is None:
        await ctx.reply("...Unban who?")
      elif member.id == ctx.author.id:
        await ctx.reply(f"...That's impossible, {ctx.author.mention}.")
      elif member.id == bot.application_id:
        await ctx.reply("I can't do that...because I'm not banned.")
      else:
        await member.unban(reason=reason)
        await ctx.reply("Done!")
    except NotFound:
      await ctx.reply(f"That member doesn't exist, {ctx.author.mention}")
    except Forbidden:
      await ctx.reply("You don't have the permission to ban a member.")
    except HTTPException:
      await ctx.reply("Uhm...Something happened, and I don't know what...Try again?")

@bot.tree.command(name="Ask KNene", description="Ask KNene and it will provide an answer.")
async def ask(ctx, question : str = None):
    if question is None:
        await ctx.reply("You can't ask KNene nothing!")
    else:
        await ctx.response.defer()

        loop = asyncio.get_running_loop()
        reply = await loop.run_in_executor(
        None,
        generate_text,
        model,
        merges,
        word_to_ix,
        ix_to_word,
        prompt,
        length=75,
        temperature=0.8
    )

    await interaction.followup.send(reply)

@bot.tree.command(name="About KNene", description="See what KNene is about.")
async def about_knene(ctx):
    embed = discord.Embed(
        title="About KNene (as of December 31, 2025)",
        description="""
        KNene is a multi-transformer block language model (LM) developed by @transmascneneisreal with assistance of ChatGPT.
        KNene is trained off of data about 9500+ words long and uses multiple writing examples (encyclopedic, dialogue, storywriting, etc.),
        however, due to current LM limitations, the data KNene is trained off of is **extremely** insufficient, which is why KNene <6.7 prints gibberish.
        KNene's training data and training time will be expanded more as it is developed.
        
        For more information about KNene, use KN-knene_specs.""",
        color=discord.Color.green()
    )
    await ctx.reply(embed=embed)

@bot.tree.command(name="KNene specs", description="View KNene's specifications")
async def knene_specs(ctx):
    embed = discord.Embed(
        title="KNene K0.5 specifications",
        description="""
        Training data size: ~9225 words, 11000-23000 tokens
        Epochs trained: 100
        Embeddings dimensions: 48
        Transformer blocks: 2
        Heads: 8
        Weights: 2
        Hidden neurons per weight: 192

        Training data: The data that KNene learns from in order to produce new data
        Epochs: How many times KNene was passed through all of the data
        Embedding dimensions: Basically, how much "meaning" a token (the numerical conversion of text) can store
        Transformer blocks: How many transformer blocks (KNene's brain) there are
        Heads: Heads are the things that focus on different parts of the training data and are added together to provide richer representation and faster (?) training
        Weights: What is being adjusted by KNene to lower differences as much as possible
        Hidden neurons: Processes text

        Includes weight tying, attention, but no memory (no recollection of past chats)""",
        color=discord.Color.green()
    )
    await ctx.reply(embed=embed)
        

level, xp, full_xp = get_global_stats()
print(f"Loaded Stats: Level {level}, XP {xp}/{full_xp}")

if __name__ == '__main__':
    if ENABLE_HEALTH:
        _start_flask_in_thread()
        print("Health endpoint enabled — remember to set ENABLE_HEALTH_SERVER=1 in Render and use an external pinger to hit health")

    if not TOKEN:
        print("Missing token. Exiting.")
    else:
        try:
            bot.run(TOKEN)
        except Exception as e:
            print(f"Bot failed to start: {e}")
