if __name__ != "__main__":
  exit()

import discord, os, random, time, json, signal, threading
from datetime import date
from discord.app_commands.errors import CommandInvokeError
from discord.embeds import Embed
from discord.ext import commands
import asyncio
from supabase import create_client, Client
from flask import Flask

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="KN-", intents=intents)
wakeup_channel_id = 1451915364396171437

TOKEN_KEY = os.getenv("KUSANAGI_APIKEY")

cuddle_cooldown = 30
last_cuddle = 0

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

def refresh_threshold():
    global member_last30
    while True:
        time.sleep(30)
        member_last30 = 0


def handle_exit_signal(*args):
    save_level_json()
    save_nenebucks_json()
    print("Bot stopped! Data saved safely 💾")
    exit(0)

signal.signal(signal.SIGINT, handle_exit_signal)
signal.signal(signal.SIGTERM, handle_exit_signal)

thread = threading.Thread(target=refresh_threshold)
thread.start()

@bot.event
async def on_ready():
  print(f'We have logged in as {bot.user}')

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
      

@bot.command()
@commands.has_permissions(administrator=True)
async def sleep(ctx):
  save_level_json()
  save_nenebucks_json()

  response_list = [
      "Ugh...already? Okay...goodnight...",
      "Eh...Do I have to?...Fine. Bye bye!",
      "Mhm, see you later!"
  ]
  await ctx.send(random.choice(response_list))

  print(f"Administrator {ctx.author} has put Nene to sleep.")

  await bot.close()

@bot.command()
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

@bot.command()
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
              "Wow, I feel bad for you."
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

@bot.command()
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

@bot.command()
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
      ctx.send(f"...Did you mean to hit me? Who's {member}?")

@bot.command()
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

@bot.command()
async def ily(ctx):
    response_list = [
        "I love you too!!",
        f"Oh, well, I love you too, {ctx.author.mention}.",
        f"*She lightly embraces {ctx.author.mention} before squeezing them tight in her arms,* I love you too!"
    ]
    await ctx.reply(random.choice(response_list))

@bot.command()
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

@bot.command()
async def stats(ctx):
  global level, xp, full_xp
  await ctx.send(f"Hmm...I'm on level {level} with {xp} XP out of {full_xp} XP...Seems too low, don't you think?")

@bot.command()
async def showcmds(ctx):
  embed = discord.Embed(
      title="I have a little bit of commands you can run, here:",
      description="""
  `KN-cuddle` : Uhm...who put this here?
  `KN-kiss (<member>)` : Kiss a member here or leave it empty to, uhh...
  `KN-hug` : Hug me.
  `KN-slap (<member>)` : Slap a member to oblivion, or leave it empty and face bad consequences!
  `KN-headpat` : Headpat me, but I am NOT a pet!
  `KN-bite (<member>)` : Bite someone, or me.
  `KN-ily` : ...Uhm...
  `KN-birthday (<member> <when>)` : Tell me when a member's birthday is, or wish me a happy birthday!
  `KN-stats` : See my stats (level, xp/max level xp)
  `KN-coinflip <bet> <pick>` : Do a coinflip; winning doubles your bet
  `KN-make_acc` : Register a new unique account
  `KN-my_acc` : View your account
  `KN-pay <member> <amount>` : Pay someone <amount> Nenebucks
  
  ------------ Admin commands -----------
  `KN-sleep` : Puts me to sleep (only admins can do this) (Graceful shutdown)
  `KN-antiraid` : Checks if there's a raid. If there is, takes proper measures""",
      color=discord.Color.green()
  )
  await ctx.send(embed=embed)

@bot.command()
async def coinflip(ctx, bet : int, pick):
    current_bal = get_balance(ctx.author.id)

    if current_bal is None:
        await ctx.reply(f"*Tsk tsk tsk*...I'm sorry, but I can't find a \"{ctx.author}\" in these files...Maybe try registering via KN-make_acc.")
        return # Stop the command here

    if bet > 0 and current_bal >= bet:
        # Deduct bet immediately (Safety first!)
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
            # Add reward (Bet * 2) back to balance
            winnings = bet * 2
            update_balance(ctx.author.id, new_bal + winnings)
        else:
            msg_to_send.description += f" Oof...you lost, {ctx.author.mention}, but hey, better luck next time."
            # No need to update balance, we already deducted the bet
        
        await msg.edit(embed=msg_to_send)
    else:
        await ctx.reply("You don't have enough Nenebucks for that bet!")

@bot.command()
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

@bot.command()
async def my_acc(ctx):
    balance = get_balance(ctx.author.id)

    if balance is not None:
        embed_var = discord.Embed(
            title = f"{ctx.author.mention}'s Account Statement *(ID: {ctx.author.id})*",
            description = f"""{balance} Nenebucks
            
            ーProvided by Kusanagi Nene♪☆""",
            color = discord.Color.green()
        )
        await ctx.send(f"*She comes back holding a stack of files* I found your file, {ctx.author.mention}.")
        await ctx.send(embed=embed_var)
    else:
        await ctx.reply(f"*She alternates from flipping through the files and licking her fingers* Hmm...I can't find a \"{ctx.author}\" here...**Try making an account with KN-make_acc.**")


@bot.command()
async def bite(ctx, member : discord.Member = None):
    if member is None:
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

@bot.command()
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

@bot.command()
async def antiraid(ctx):
    pass

level, xp, full_xp = get_global_stats()
print(f"Loaded Stats: Level {level}, XP {xp}/{full_xp}")

server = Flask('')

@server.route('/')
def home():
    return "Nene is awake and watching! 👀"

def run():
    server.run(host='0.0.0.0', port=10000)

def keep_alive():
    t = Thread(target=run)
    t.start()
  
keep_alive()
bot.run(TOKEN_KEY)
