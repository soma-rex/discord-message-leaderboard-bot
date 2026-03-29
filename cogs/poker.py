import random
import time
from collections import Counter
from itertools import combinations

import discord
from discord import app_commands
from discord.ext import commands


# ─────────────────────────────────────────────
# CONSTANTS — swap these IDs once you upload
# the custom emojis to your server
# ─────────────────────────────────────────────
CHIP_EMOJI  = "<:poker_chip:1487837444685430896>"   # replace with <:poker_chip:ID>  once uploaded
SPADE_EMOJI = "<:spade:1487837442907050197>"   # replace with <:spade:ID>
HEART_EMOJI = "<:heart:1487837441535508591>"   # replace with <:heart:ID>
DIAM_EMOJI  = "<:diamond:1487837439967105075>"   # replace with <:diamond:ID>
CLUB_EMOJI  = "<:club:1487837438083862698>"   # replace with <:club:ID>

SUITS      = ["♠", "♥", "♦", "♣"]
RANKS      = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
RANK_VALUE = {r: i for i, r in enumerate(RANKS, start=2)}

HAND_NAMES = {
    8: "Straight Flush",
    7: "Four of a Kind",
    6: "Full House",
    5: "Flush",
    4: "Straight",
    3: "Three of a Kind",
    2: "Two Pair",
    1: "One Pair",
    0: "High Card",
}

PHASE_COLORS = {
    "preflop":  discord.Color.blurple(),
    "flop":     discord.Color.blue(),
    "turn":     discord.Color.orange(),
    "river":    discord.Color.red(),
    "showdown": discord.Color.gold(),
}

def is_owner(interaction: discord.Interaction) -> bool:
    return interaction.user.id == 720550790036455444


# ─────────────────────────────────────────────
# DECK HELPERS
# ─────────────────────────────────────────────
def build_deck():
    deck = [f"{rank}{suit}" for suit in SUITS for rank in RANKS]
    random.shuffle(deck)
    return deck

def card_rank(card: str) -> str:
    return card[:-1]

def card_suit(card: str) -> str:
    return card[-1]


# ─────────────────────────────────────────────
# HAND EVALUATOR
# ─────────────────────────────────────────────
def _score_five(cards):
    ranks   = [card_rank(c) for c in cards]
    suits   = [card_suit(c) for c in cards]
    vals    = sorted([RANK_VALUE[r] for r in ranks], reverse=True)
    counts  = Counter(ranks)
    freq    = sorted(counts.values(), reverse=True)
    is_flush    = len(set(suits)) == 1
    is_straight = len(set(vals)) == 5 and vals[0] - vals[4] == 4
    if set(vals) == {14, 2, 3, 4, 5}:
        is_straight = True
        vals = [5, 4, 3, 2, 1]
    if is_straight and is_flush:
        return (8, vals)
    if freq[0] == 4:
        quad_val = RANK_VALUE[max(counts, key=lambda r: (counts[r], RANK_VALUE[r]))]
        kickers  = sorted([v for v in vals if v != quad_val], reverse=True)
        return (7, [quad_val] + kickers)
    if freq[:2] == [3, 2]:
        trip_val = RANK_VALUE[next(r for r, c in counts.items() if c == 3)]
        pair_val = RANK_VALUE[next(r for r, c in counts.items() if c == 2)]
        return (6, [trip_val, pair_val])
    if is_flush:
        return (5, vals)
    if is_straight:
        return (4, vals)
    if freq[0] == 3:
        trip_val = RANK_VALUE[next(r for r, c in counts.items() if c == 3)]
        kickers  = sorted([RANK_VALUE[r] for r, c in counts.items() if c != 3], reverse=True)
        return (3, [trip_val] + kickers)
    if freq[:2] == [2, 2]:
        pairs   = sorted([RANK_VALUE[r] for r, c in counts.items() if c == 2], reverse=True)
        kicker  = max(RANK_VALUE[r] for r, c in counts.items() if c == 1)
        return (2, pairs + [kicker])
    if freq[0] == 2:
        pair_val = RANK_VALUE[next(r for r, c in counts.items() if c == 2)]
        kickers  = sorted([RANK_VALUE[r] for r, c in counts.items() if c == 1], reverse=True)
        return (1, [pair_val] + kickers)
    return (0, vals)

def evaluate_hand(cards):
    if len(cards) <= 5:
        return _score_five(cards)
    return max(_score_five(list(c)) for c in combinations(cards, 5))

def hand_name(score_tuple) -> str:
    return HAND_NAMES.get(score_tuple[0], "Unknown")


# ─────────────────────────────────────────────
# SIDE POTS
# ─────────────────────────────────────────────
def build_side_pots(game: dict):
    contributions = {
        uid: p["total_bet"]
        for uid, p in game["players"].items()
        if p["total_bet"] > 0
    }
    pots = []
    while contributions:
        min_bet  = min(contributions.values())
        involved = list(contributions.keys())
        pots.append({
            "amount":   min_bet * len(involved),
            "eligible": [uid for uid in involved if not game["players"][uid]["folded"]],
        })
        contributions = {uid: amt - min_bet for uid, amt in contributions.items() if amt - min_bet > 0}
    return pots


# ─────────────────────────────────────────────
# EMBED BUILDERS
# ─────────────────────────────────────────────
def build_game_embed(game: dict, guild: discord.Guild | None = None) -> discord.Embed:
    """Main game state embed — sent each action."""
    phase       = game["phase"].title()
    current_uid = game["player_order"][game["turn_index"]]
    board       = " ".join(game["visible_community"]) or "*(cards hidden)*"

    color = PHASE_COLORS.get(game["phase"], discord.Color.blurple())
    embed = discord.Embed(
        title=f"{SPADE_EMOJI} {HEART_EMOJI} Texas Hold'em  ·  {phase} {DIAM_EMOJI} {CLUB_EMOJI}",
        color=color,
    )

    embed.add_field(name="🃏  Board", value=board, inline=False)
    embed.add_field(name=f"{CHIP_EMOJI}  Pot",         value=f"**{game['pot']}**",          inline=True)
    embed.add_field(name="📊  Current bet",             value=f"**{game['current_bet']}**",  inline=True)
    embed.add_field(name="🎯  Acting",                  value=f"<@{current_uid}>",            inline=True)
    embed.set_footer(text='Press "Players" to see everyone\'s status')
    return embed


def build_players_embed(game: dict) -> discord.Embed:
    """Shown when the Players button is pressed (ephemeral)."""
    current_uid = game["player_order"][game["turn_index"]]
    embed = discord.Embed(title="👥  Players at the table", color=discord.Color.dark_grey())
    lines = []
    for uid in game["player_order"]:
        p = game["players"][uid]
        if p["folded"]:
            icon, note = "❌", "folded"
        elif p.get("all_in"):
            icon, note = "💥", f"all-in  (bet {p['bet']})"
        else:
            icon, note = "🟢", f"bet {p['bet']}"
        turn = "  ◀ **their turn**" if uid == current_uid else ""
        lines.append(f"{icon}  <@{uid}>  —  {note}{turn}")
    embed.description = "\n".join(lines)
    return embed


# ─────────────────────────────────────────────
# SHOWDOWN
# ─────────────────────────────────────────────
async def finish_poker_game(channel: discord.TextChannel, game: dict, cog: "PokerCog"):
    pots          = build_side_pots(game)
    results_lines = []
    players       = game["players"]

    for i, pot in enumerate(pots):
        eligible = [uid for uid in pot["eligible"] if not players[uid]["folded"]]
        if not eligible:
            continue
        scored = []
        for uid in eligible:
            score = evaluate_hand(players[uid]["cards"] + game["community"])
            scored.append((score, uid, players[uid]["cards"]))
        scored.sort(key=lambda x: x[0], reverse=True)
        best      = scored[0][0]
        winners   = [s for s in scored if s[0] == best]
        split     = pot["amount"] // len(winners)
        remainder = pot["amount"] % len(winners)
        for idx, (_, uid, _) in enumerate(winners):
            cog.add_chips(uid, split + (remainder if idx == 0 else 0))
        winner_names = []
        for _, uid, _ in winners:
            try:
                m = await channel.guild.fetch_member(uid)
                winner_names.append(m.display_name)
            except Exception:
                winner_names.append(f"<@{uid}>")
        label = f"Pot {i+1}" if len(pots) > 1 else "Pot"
        results_lines.append(f"**{label}  ({pot['amount']} chips)** → {', '.join(winner_names)}")

    # build hands section
    hand_lines = []
    for uid, data in players.items():
        if data["folded"]:
            continue
        score = evaluate_hand(data["cards"] + game["community"])
        try:
            m    = await channel.guild.fetch_member(uid)
            name = m.display_name
        except Exception:
            name = f"<@{uid}>"
        hand_lines.append(f"**{name}** — {' '.join(data['cards'])}  ·  *{hand_name(score)}*")

    embed = discord.Embed(title="🏆  Showdown!", color=discord.Color.gold())
    embed.add_field(name="🃏  Board",      value=" ".join(game["community"]),    inline=False)
    embed.add_field(name="🥇  Results",   value="\n".join(results_lines),       inline=False)
    embed.add_field(name="🂠  All Hands", value="\n".join(hand_lines),           inline=False)

    await channel.send(embed=embed)
    if channel.id in cog.poker_games:
        del cog.poker_games[channel.id]


# ─────────────────────────────────────────────
# PLAYERS BUTTON (standalone — shows status)
# ─────────────────────────────────────────────
class PlayersButton(discord.ui.View):
    """A lightweight view with only the Players button — attached to game embeds."""
    def __init__(self, channel_id: int, cog: "PokerCog"):
        super().__init__(timeout=None)
        self.channel_id = channel_id
        self.cog        = cog

    @discord.ui.button(label="👥 Players", style=discord.ButtonStyle.secondary, row=0)
    async def show_players(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = self.cog.poker_games.get(self.channel_id)
        if not game:
            await interaction.response.send_message("No active game.", ephemeral=True)
            return
        await interaction.response.send_message(embed=build_players_embed(game), ephemeral=True)


# ─────────────────────────────────────────────
# BETTING VIEW  (action buttons + Players)
# ─────────────────────────────────────────────
class PokerBetView(discord.ui.View):
    def __init__(self, channel_id: int, game: dict, cog: "PokerCog"):
        super().__init__(timeout=300)
        self.channel_id = channel_id
        self.game       = game
        self.cog        = cog

    async def on_timeout(self):
        if self.channel_id in self.cog.poker_games:
            del self.cog.poker_games[self.channel_id]

    def get_game(self):
        return self.cog.poker_games.get(self.channel_id)

    # ── guard ──────────────────────────────────
    def _guard(self, interaction: discord.Interaction):
        game = self.get_game()
        if not game:
            return None, None, "No active game."
        current = game["player_order"][game["turn_index"]]
        if interaction.user.id != current:
            return game, None, "It's not your turn."
        player = game["players"].get(interaction.user.id)
        if not player or player["folded"]:
            return game, None, "You're not active in this hand."
        if player.get("all_in"):
            return game, None, "You are all-in — nothing to do."
        if player["acted"]:
            return game, None, "You already acted this round."
        return game, player, None

    def _advance_turn_index(self, game: dict):
        n = len(game["player_order"])
        for i in range(1, n + 1):
            nxt = (game["turn_index"] + i) % n
            uid = game["player_order"][nxt]
            p   = game["players"][uid]
            if not p["folded"] and not p.get("all_in"):
                game["turn_index"] = nxt
                return

    # ── phase advancement ──────────────────────
    async def advance_phase(self, channel: discord.TextChannel):
        game = self.get_game()
        if not game:
            return

        phases = ["preflop", "flop", "turn", "river", "showdown"]
        idx    = phases.index(game["phase"])
        game["phase"] = phases[idx + 1]

        if game["phase"] == "flop":
            game["visible_community"] = game["community"][:3]
        elif game["phase"] == "turn":
            game["visible_community"] = game["community"][:4]
        elif game["phase"] == "river":
            game["visible_community"] = game["community"][:5]
        elif game["phase"] == "showdown":
            await finish_poker_game(channel, game, self.cog)
            return

        # reset street
        game["current_bet"] = 0
        for p in game["players"].values():
            p["bet"] = 0
            if not p["folded"] and not p.get("all_in"):
                p["acted"] = False

        alive   = [p for p in game["players"].values() if not p["folded"]]
        can_act = [p for p in alive if not p.get("all_in")]

        if len(can_act) == 0:
            game["visible_community"] = game["community"]
            game["phase"]             = "showdown"
            await finish_poker_game(channel, game, self.cog)
            return

        if len(can_act) <= 1:
            await self.advance_phase(channel)
            return

        alive_order       = [uid for uid in game["player_order"] if not game["players"][uid]["folded"]]
        game["turn_index"] = game["player_order"].index(alive_order[0])

        current_uid = game["player_order"][game["turn_index"]]
        view        = PokerBetView(self.channel_id, game, self.cog)
        embed       = build_game_embed(game)
        await channel.send(f"<@{current_uid}>", embed=embed, view=view)

    # ── resolve after every action ─────────────
    async def resolve_turn(self, channel: discord.TextChannel):
        game = self.get_game()
        if not game:
            return

        alive_users = [uid for uid, p in game["players"].items() if not p["folded"]]
        if len(alive_users) == 1:
            winner_id = alive_users[0]
            self.cog.add_chips(winner_id, game["pot"])
            try:
                m    = await channel.guild.fetch_member(winner_id)
                name = m.display_name
            except Exception:
                name = f"<@{winner_id}>"
            embed = discord.Embed(
                title=f"🏆  {name} wins!",
                description=f"Everyone else folded.\n{CHIP_EMOJI} **{game['pot']} chips** awarded.",
                color=discord.Color.gold(),
            )
            await channel.send(embed=embed)
            del self.cog.poker_games[self.channel_id]
            return

        alive   = [p for p in game["players"].values() if not p["folded"]]
        can_act = [p for p in alive if not p.get("all_in")]
        bets_level = all(p["bet"] == game["current_bet"] for p in can_act)
        all_acted  = all(p["acted"] for p in can_act)

        if (not can_act) or (all_acted and bets_level):
            await self.advance_phase(channel)
            return

        current_uid = game["player_order"][game["turn_index"]]
        new_view    = PokerBetView(self.channel_id, game, self.cog)
        embed       = build_game_embed(game)
        await channel.send(f"<@{current_uid}>", embed=embed, view=new_view)

    # ── FOLD ──────────────────────────────────
    @discord.ui.button(label="Fold", style=discord.ButtonStyle.danger, row=0)
    async def fold(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, player, err = self._guard(interaction)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        player["folded"] = True
        player["acted"]  = True
        self._advance_turn_index(game)
        await interaction.response.send_message("❌ You folded.", ephemeral=True)
        await self.resolve_turn(interaction.channel)

    # ── CHECK ─────────────────────────────────
    @discord.ui.button(label="Check", style=discord.ButtonStyle.secondary, row=0)
    async def check(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, player, err = self._guard(interaction)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        if game["current_bet"] != player["bet"]:
            await interaction.response.send_message(
                f"Can't check — there is a bet of **{game['current_bet']}**. Call or raise.",
                ephemeral=True,
            )
            return
        player["acted"] = True
        self._advance_turn_index(game)
        await interaction.response.send_message("✅ Checked.", ephemeral=True)
        await self.resolve_turn(interaction.channel)

    # ── CALL ──────────────────────────────────
    @discord.ui.button(label="Call", style=discord.ButtonStyle.primary, row=0)
    async def call(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, player, err = self._guard(interaction)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        amount = game["current_bet"] - player["bet"]
        if amount <= 0:
            await interaction.response.send_message("Nothing to call — use Check.", ephemeral=True)
            return
        chips = self.cog.get_chips(interaction.user.id)
        if chips <= 0:
            await interaction.response.send_message("You have no chips.", ephemeral=True)
            return
        if chips < amount:
            amount             = chips
            player["all_in"]   = True
        self.cog.remove_chips(interaction.user.id, amount)
        player["bet"]       += amount
        player["total_bet"] += amount
        game["pot"]         += amount
        player["acted"]      = True
        self._advance_turn_index(game)
        suffix = "  *(All-in!)*" if player.get("all_in") else ""
        await interaction.response.send_message(f"☎️ Called **{amount}**.{suffix}", ephemeral=True)
        await self.resolve_turn(interaction.channel)

    # ── RAISE +100 ────────────────────────────
    @discord.ui.button(label="Raise +100", style=discord.ButtonStyle.success, row=1)
    async def raise_bet(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, player, err = self._guard(interaction)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        target = game["current_bet"] + 100
        amount = target - player["bet"]
        if amount <= 0:
            await interaction.response.send_message("Invalid raise amount.", ephemeral=True)
            return
        if not self.cog.remove_chips(interaction.user.id, amount):
            await interaction.response.send_message("Not enough chips — try All-In.", ephemeral=True)
            return
        game["current_bet"]  = target
        player["bet"]        = target
        player["total_bet"] += amount
        game["pot"]         += amount
        player["acted"]      = True
        for uid, p in game["players"].items():
            if uid != interaction.user.id and not p["folded"] and not p.get("all_in"):
                p["acted"] = False
        self._advance_turn_index(game)
        await interaction.response.send_message(f"📈 Raised to **{target}**.", ephemeral=True)
        await self.resolve_turn(interaction.channel)

    # ── ALL-IN ────────────────────────────────
    @discord.ui.button(label="All-In 💥", style=discord.ButtonStyle.danger, row=1)
    async def all_in(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, player, err = self._guard(interaction)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        chips = self.cog.get_chips(interaction.user.id)
        if chips <= 0:
            await interaction.response.send_message("You have no chips.", ephemeral=True)
            return
        self.cog.remove_chips(interaction.user.id, chips)
        player["bet"]       += chips
        player["total_bet"] += chips
        game["pot"]         += chips
        player["all_in"]     = True
        player["acted"]      = True
        if player["bet"] > game["current_bet"]:
            game["current_bet"] = player["bet"]
            for uid, p in game["players"].items():
                if uid != interaction.user.id and not p["folded"] and not p.get("all_in"):
                    p["acted"] = False
        self._advance_turn_index(game)
        await interaction.response.send_message(f"💥 All-in with **{chips}** chips!", ephemeral=True)
        await self.resolve_turn(interaction.channel)

    # ── PLAYERS ───────────────────────────────
    @discord.ui.button(label="👥 Players", style=discord.ButtonStyle.secondary, row=1)
    async def show_players(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = self.get_game()
        if not game:
            await interaction.response.send_message("No active game.", ephemeral=True)
            return
        await interaction.response.send_message(embed=build_players_embed(game), ephemeral=True)


# ─────────────────────────────────────────────
# COG
# ─────────────────────────────────────────────
class PokerCog(commands.Cog, name="Poker"):
    """Texas Hold'em poker with chips."""

    def __init__(self, bot: commands.Bot):
        self.bot         = bot
        self.poker_games: dict = {}
        self.conn        = bot.conn
        self.cursor      = bot.cursor
        self._ensure_table()

    def _ensure_table(self):
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS poker_chips (
                user_id    INTEGER PRIMARY KEY,
                chips      INTEGER NOT NULL DEFAULT 1000,
                last_daily INTEGER DEFAULT 0
            )
            """
        )
        self.conn.commit()

    def ensure_chips(self, user_id: int):
        self.cursor.execute(
            "INSERT OR IGNORE INTO poker_chips (user_id, chips, last_daily) VALUES (?, 1000, 0)",
            (user_id,),
        )
        self.conn.commit()

    def get_chips(self, user_id: int) -> int:
        self.ensure_chips(user_id)
        self.cursor.execute("SELECT chips FROM poker_chips WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone()[0]

    def add_chips(self, user_id: int, amount: int):
        self.ensure_chips(user_id)
        self.cursor.execute(
            "UPDATE poker_chips SET chips = chips + ? WHERE user_id = ?", (amount, user_id)
        )
        self.conn.commit()

    def remove_chips(self, user_id: int, amount: int) -> bool:
        chips = self.get_chips(user_id)
        if chips < amount:
            return False
        self.cursor.execute(
            "UPDATE poker_chips SET chips = chips - ? WHERE user_id = ?", (amount, user_id)
        )
        self.conn.commit()
        return True

    poker_group = app_commands.Group(name="poker", description="Texas Hold'em with chips")

    # ── /daily ────────────────────────────────
    @app_commands.command(name="daily", description="Claim your daily poker chips")
    async def daily(self, interaction: discord.Interaction):
        self.ensure_chips(interaction.user.id)
        self.cursor.execute(
            "SELECT last_daily FROM poker_chips WHERE user_id = ?", (interaction.user.id,)
        )
        last_daily = self.cursor.fetchone()[0]
        now        = int(time.time())

        if now - last_daily < 86400:
            remaining = 86400 - (now - last_daily)
            h, m      = remaining // 3600, (remaining % 3600) // 60
            embed = discord.Embed(
                title="⏳  Daily not ready",
                description=f"Come back in **{h}h {m}m** for your next reward.",
                color=discord.Color.orange(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        reward = random.randint(300, 700)
        self.add_chips(interaction.user.id, reward)
        self.cursor.execute(
            "UPDATE poker_chips SET last_daily = ? WHERE user_id = ?", (now, interaction.user.id)
        )
        self.conn.commit()
        total = self.get_chips(interaction.user.id)

        embed = discord.Embed(
            title="💰  Daily reward claimed!",
            color=discord.Color.green(),
        )
        embed.add_field(name=f"{CHIP_EMOJI}  Reward",  value=f"**+{reward}**",   inline=True)
        embed.add_field(name="💼  New balance",         value=f"**{total}**",     inline=True)
        embed.set_footer(text=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    # ── /poker chips ──────────────────────────
    @poker_group.command(name="chips", description="Check your chip balance")
    async def poker_chips(self, interaction: discord.Interaction):
        chips = self.get_chips(interaction.user.id)
        embed = discord.Embed(
            title=f"{CHIP_EMOJI}  Chip Balance",
            color=discord.Color.gold(),
        )
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url,
        )
        embed.description = f"**{chips:,}** chips"
        embed.set_footer(text="Use /daily to claim free chips every 24h")
        await interaction.response.send_message(embed=embed)

    # ── /poker create ─────────────────────────
    @poker_group.command(name="create", description="Create a poker table")
    async def poker_create(self, interaction: discord.Interaction, buy_in: int = 100):
        channel_id = interaction.channel.id
        if channel_id in self.poker_games:
            await interaction.response.send_message("A game is already active here.", ephemeral=True)
            return
        self.poker_games[channel_id] = {
            "host":              interaction.user.id,
            "buy_in":            buy_in,
            "players":           {},
            "deck":              [],
            "community":         [],
            "visible_community": [],
            "pot":               0,
            "phase":             "waiting",
            "current_bet":       0,
            "player_order":      [],
            "turn_index":        0,
        }
        embed = discord.Embed(
            title=f"{SPADE_EMOJI} {HEART_EMOJI}  Poker Table Open  {DIAM_EMOJI} {CLUB_EMOJI}",
            description=(
                f"Buy-in: **{buy_in}** {CHIP_EMOJI}\n\n"
                "Use `/poker join` to take a seat.\n"
                "Host uses `/poker start` when everyone is ready."
            ),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Hosted by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)

    # ── /poker join ───────────────────────────
    @poker_group.command(name="join", description="Join the current poker table")
    async def poker_join(self, interaction: discord.Interaction):
        game = self.poker_games.get(interaction.channel.id)
        if not game or game["phase"] != "waiting":
            await interaction.response.send_message("No joinable table here.", ephemeral=True)
            return
        if interaction.user.id in game["players"]:
            await interaction.response.send_message("You're already seated.", ephemeral=True)
            return
        buy_in = game["buy_in"]
        if not self.remove_chips(interaction.user.id, buy_in):
            await interaction.response.send_message(
                f"Not enough chips — you need **{buy_in}**.", ephemeral=True
            )
            return
        game["players"][interaction.user.id] = {
            "cards": [], "folded": False, "bet": 0,
            "acted": False, "total_bet": 0, "all_in": False,
        }
        game["pot"] += buy_in

        embed = discord.Embed(
            description=f"✅  {interaction.user.mention} joined the table!  {CHIP_EMOJI} Pot: **{game['pot']}**",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    # ── /poker start ──────────────────────────
    @poker_group.command(name="start", description="Start the game (host only)")
    async def poker_start(self, interaction: discord.Interaction):
        game = self.poker_games.get(interaction.channel.id)
        if not game:
            await interaction.response.send_message("No table here.", ephemeral=True)
            return
        if interaction.user.id != game["host"]:
            await interaction.response.send_message("Only the host can start.", ephemeral=True)
            return
        if len(game["players"]) < 2:
            await interaction.response.send_message("Need at least 2 players.", ephemeral=True)
            return

        deck             = build_deck()
        game["deck"]     = deck
        game["community"]= [deck.pop() for _ in range(5)]
        game["visible_community"] = []
        game["phase"]    = "preflop"
        game["current_bet"] = 0

        await interaction.response.defer()

        for user_id, p in game["players"].items():
            p.update({
                "cards": [deck.pop(), deck.pop()],
                "folded": False, "bet": 0,
                "acted": False, "total_bet": 0, "all_in": False,
            })
            try:
                member = await interaction.guild.fetch_member(user_id)
                await member.send(
                    f"🃏  Your hole cards: **{' '.join(p['cards'])}**\n"
                    f"*(Keep these secret!)*"
                )
            except Exception:
                pass

        game["player_order"] = list(game["players"].keys())
        game["turn_index"]   = 0
        current_uid          = game["player_order"][0]

        view  = PokerBetView(interaction.channel.id, game, self)
        embed = build_game_embed(game)
        await interaction.followup.send(f"<@{current_uid}>", embed=embed, view=view)

    # ── /poker setchips ───────────────────────
    @poker_group.command(name="setchips", description="Add or remove chips (admin)")
    @app_commands.check(is_owner)
    async def poker_setchips(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        self.ensure_chips(user.id)
        self.cursor.execute(
            "UPDATE poker_chips SET chips = chips + ? WHERE user_id = ?", (amount, user.id)
        )
        self.conn.commit()
        total = self.get_chips(user.id)
        embed = discord.Embed(
            title=f"{CHIP_EMOJI}  Chips updated",
            color=discord.Color.green() if amount >= 0 else discord.Color.red(),
        )
        embed.add_field(name="Player",      value=user.mention,      inline=True)
        embed.add_field(name="Change",      value=f"**{amount:+}**", inline=True)
        embed.add_field(name="New balance", value=f"**{total:,}**",  inline=True)
        await interaction.response.send_message(embed=embed)

    # ── /poker end ────────────────────────────
    @poker_group.command(name="end", description="Force-end the current game (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def poker_end(self, interaction: discord.Interaction):
        if interaction.channel.id not in self.poker_games:
            await interaction.response.send_message("No active game here.", ephemeral=True)
            return
        del self.poker_games[interaction.channel.id]
        embed = discord.Embed(
            title="🛑  Game ended",
            description="The poker game has been force-ended by an admin.",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(PokerCog(bot))