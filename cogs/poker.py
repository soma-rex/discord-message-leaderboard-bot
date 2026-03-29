import random
import time
from collections import Counter
from itertools import combinations

import discord
from discord import app_commands
from discord.ext import commands


# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────
SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
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
# FULL HAND EVALUATOR  (best 5 from N cards)
# ─────────────────────────────────────────────
def _score_five(cards):
    ranks = [card_rank(c) for c in cards]
    suits = [card_suit(c) for c in cards]
    vals = sorted([RANK_VALUE[r] for r in ranks], reverse=True)
    counts = Counter(ranks)
    freq = sorted(counts.values(), reverse=True)
    is_flush = len(set(suits)) == 1
    is_straight = len(set(vals)) == 5 and vals[0] - vals[4] == 4
    # wheel: A-2-3-4-5
    if set(vals) == {14, 2, 3, 4, 5}:
        is_straight = True
        vals = [5, 4, 3, 2, 1]

    if is_straight and is_flush:
        return (8, vals)
    if freq[0] == 4:
        quad_val = RANK_VALUE[max(counts, key=lambda r: (counts[r], RANK_VALUE[r]))]
        kickers = sorted([v for v in vals if v != quad_val], reverse=True)
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
        kickers = sorted([RANK_VALUE[r] for r, c in counts.items() if c != 3], reverse=True)
        return (3, [trip_val] + kickers)
    if freq[:2] == [2, 2]:
        pairs = sorted([RANK_VALUE[r] for r, c in counts.items() if c == 2], reverse=True)
        kicker = max(RANK_VALUE[r] for r, c in counts.items() if c == 1)
        return (2, pairs + [kicker])
    if freq[0] == 2:
        pair_val = RANK_VALUE[next(r for r, c in counts.items() if c == 2)]
        kickers = sorted([RANK_VALUE[r] for r, c in counts.items() if c == 1], reverse=True)
        return (1, [pair_val] + kickers)
    return (0, vals)


def evaluate_hand(cards):
    if len(cards) <= 5:
        return _score_five(cards)
    return max(_score_five(list(combo)) for combo in combinations(cards, 5))


def hand_name(score_tuple) -> str:
    return HAND_NAMES.get(score_tuple[0], "Unknown")


# ─────────────────────────────────────────────
# STATUS MESSAGE
# ─────────────────────────────────────────────
def build_status(game: dict) -> str:
    board = " ".join(game["visible_community"]) or "No cards yet"
    current_uid = game["player_order"][game["turn_index"]]
    phase = game["phase"].title()
    lines = [
        f"🃏 **{phase}** | Pot: **{game['pot']}** | Current bet: **{game['current_bet']}**",
        f"Board: {board}",
        f"🎯 Turn: <@{current_uid}>",
        "",
    ]
    for uid in game["player_order"]:
        p = game["players"][uid]
        if p["folded"]:
            status = "❌ folded"
        elif p.get("all_in"):
            status = f"💥 all-in (bet {p['bet']})"
        else:
            status = f"bet {p['bet']}"
        arrow = " ◀" if uid == current_uid else ""
        lines.append(f"  <@{uid}> — {status}{arrow}")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# SHOWDOWN
# ─────────────────────────────────────────────
def build_side_pots(game: dict):
    players = game["players"]

    # Only players who put money in
    contributions = {
        uid: p["bet"]
        for uid, p in players.items()
        if p["bet"] > 0
    }

    pots = []

    while contributions:
        # smallest contribution (layer)
        min_bet = min(contributions.values())

        # players contributing to this pot
        involved = list(contributions.keys())

        pot_amount = min_bet * len(involved)

        pots.append({
            "amount": pot_amount,
            "eligible": [uid for uid in involved if not players[uid]["folded"]]
        })

        # subtract layer
        new_contributions = {}
        for uid, amt in contributions.items():
            remaining = amt - min_bet
            if remaining > 0:
                new_contributions[uid] = remaining

        contributions = new_contributions

    return pots

async def finish_poker_game(channel: discord.TextChannel, game: dict, cog: "PokerCog"):
    players = game["players"]

    # build pots
    pots = build_side_pots(game)

    results_text = []
    total_distributed = 0

    for i, pot in enumerate(pots):
        eligible = [uid for uid in pot["eligible"] if not players[uid]["folded"]]

        if not eligible:
            continue

        scored = []
        for uid in eligible:
            data = players[uid]
            all_cards = data["cards"] + game["community"]
            score = evaluate_hand(all_cards)
            scored.append((score, uid, data["cards"]))

        scored.sort(key=lambda x: x[0], reverse=True)

        best_score = scored[0][0]
        winners = [s for s in scored if s[0] == best_score]

        split_amount = pot["amount"] // len(winners)

        for _, uid, _ in winners:
            cog.add_chips(uid, split_amount)

        # FIX remainder
        remainder = pot["amount"] % len(winners)
        if remainder > 0:
            cog.add_chips(winners[0][1], remainder)

        # names for display
        winner_names = []
        for _, uid, _ in winners:
            try:
                m = await channel.guild.fetch_member(uid)
                winner_names.append(m.display_name)
            except:
                winner_names.append(f"<@{uid}>")

        results_text.append(
            f"Pot {i+1}: **{pot['amount']}** → {', '.join(winner_names)}"
        )

    # 🏆 build embed
    embed = discord.Embed(title="🏆 Showdown!", color=discord.Color.gold())
    embed.add_field(name="Board", value=" ".join(game["community"]), inline=False)
    embed.add_field(name="Pot Results", value="\n".join(results_text), inline=False)

    # show all hands
    hand_lines = []
    for uid, data in players.items():
        if data["folded"]:
            continue
        score = evaluate_hand(data["cards"] + game["community"])
        try:
            m = await channel.guild.fetch_member(uid)
            name = m.display_name
        except:
            name = f"<@{uid}>"

        hand_lines.append(
            f"{name}: {' '.join(data['cards'])} — **{hand_name(score)}**"
        )

    embed.add_field(name="All Hands", value="\n".join(hand_lines), inline=False)

    await channel.send(embed=embed)

    if channel.id in cog.poker_games:
        del cog.poker_games[channel.id]


# ─────────────────────────────────────────────
# BETTING VIEW
# ─────────────────────────────────────────────
class PokerBetView(discord.ui.View):
    def __init__(self, channel_id: int, game: dict, cog: "PokerCog"):
        super().__init__(timeout=300)
        self.channel_id = channel_id
        self.game = game
        self.cog = cog

    async def on_timeout(self):
        if self.channel_id in self.cog.poker_games:
            del self.cog.poker_games[self.channel_id]

    def get_game(self):
        return self.cog.poker_games.get(self.channel_id)

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
            return game, None, "You are all-in, nothing to do."
        if player["acted"]:
            return game, None, "You already acted this round."
        return game, player, None

    def _advance_turn_index(self, game: dict, acted_uid: int):
        n = len(game["player_order"])

        for i in range(1, n + 1):
            next_index = (game["turn_index"] + i) % n
            uid = game["player_order"][next_index]
            p = game["players"][uid]

            if not p["folded"] and not p.get("all_in"):
                game["turn_index"] = next_index
                return

    async def advance_phase(self, channel: discord.TextChannel):
        game = self.get_game()
        if not game:
            return

        phases = ["preflop", "flop", "turn", "river", "showdown"]
        idx = phases.index(game["phase"])
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

        game["current_bet"] = 0
        for p in game["players"].values():
            p["bet"] = 0
            if not p["folded"] and not p.get("all_in"):
                p["acted"] = False

        alive = [p for p in game["players"].values() if not p["folded"]]
        can_act = [p for p in alive if not p.get("all_in")]

        # 🔥 FORCE SHOWDOWN IF NO ONE CAN ACT
        if len(can_act) == 0:
            game["visible_community"] = game["community"]  # reveal all cards
            game["phase"] = "showdown"
            await finish_poker_game(channel, game, self.cog)
            return

        if len(can_act) <= 1:
            await self.advance_phase(channel)
            return



        alive_order = [uid for uid in game["player_order"] if not game["players"][uid]["folded"]]
        game["turn_index"] = game["player_order"].index(alive_order[0])

        new_view = PokerBetView(self.channel_id, game, self.cog)
        await channel.send(build_status(game), view=new_view)

    async def resolve_turn(self, channel: discord.TextChannel):
        game = self.get_game()
        if not game:
            return

        alive_users = [uid for uid, p in game["players"].items() if not p["folded"]]
        if len(alive_users) == 1:
            winner_id = alive_users[0]
            self.cog.add_chips(winner_id, game["pot"])
            try:
                m = await channel.guild.fetch_member(winner_id)
                name = m.display_name
            except Exception:
                name = f"<@{winner_id}>"
            await channel.send(f"🏆 **{name}** wins by fold and gets **{game['pot']}** chips!")
            del self.cog.poker_games[self.channel_id]
            return

        alive = [p for p in game["players"].values() if not p["folded"]]
        can_act = [p for p in alive if not p.get("all_in")]
        bets_level = all(p["bet"] == game["current_bet"] for p in can_act)
        all_acted = all(p["acted"] for p in can_act)

        if (not can_act) or (all_acted and bets_level):
            await self.advance_phase(channel)
            return

        new_view = PokerBetView(self.channel_id, game, self.cog)
        await channel.send(build_status(game), view=new_view)

    # ── FOLD ──────────────────────────────────
    @discord.ui.button(label="Fold", style=discord.ButtonStyle.danger, row=0)
    async def fold(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, player, err = self._guard(interaction)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        player["folded"] = True
        player["acted"] = True
        self._advance_turn_index(game, interaction.user.id)
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
                f"Can't check — current bet is **{game['current_bet']}**. Call or raise.", ephemeral=True
            )
            return
        player["acted"] = True
        self._advance_turn_index(game, interaction.user.id)
        await interaction.response.send_message("✅ You checked.", ephemeral=True)
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
            amount = chips
            player["all_in"] = True
        self.cog.remove_chips(interaction.user.id, amount)
        player["bet"] += amount
        game["pot"] += amount
        player["acted"] = True
        self._advance_turn_index(game, interaction.user.id)
        suffix = " (All-in!)" if player.get("all_in") else ""
        await interaction.response.send_message(f"☎️ You called **{amount}**.{suffix}", ephemeral=True)
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
        if not self.cog.remove_chips(interaction.user.id, amount):
            await interaction.response.send_message("Not enough chips — use All-In.", ephemeral=True)
            return
        game["current_bet"] = target
        player["bet"] = target
        game["pot"] += amount
        player["acted"] = True
        for uid, p in game["players"].items():
            if uid != interaction.user.id and not p["folded"] and not p.get("all_in"):
                p["acted"] = False
        self._advance_turn_index(game, interaction.user.id)
        await interaction.response.send_message(f"📈 You raised to **{target}**.", ephemeral=True)
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
            await interaction.response.send_message("You have no chips left.", ephemeral=True)
            return
        self.cog.remove_chips(interaction.user.id, chips)
        player["bet"] += chips
        game["pot"] += chips
        player["all_in"] = True
        player["acted"] = True
        if player["bet"] > game["current_bet"]:
            game["current_bet"] = player["bet"]
            for uid, p in game["players"].items():
                if uid != interaction.user.id and not p["folded"] and not p.get("all_in"):
                    p["acted"] = False
        self._advance_turn_index(game, interaction.user.id)
        await interaction.response.send_message(f"💥 All-in with **{chips}** chips!", ephemeral=True)
        await self.resolve_turn(interaction.channel)


# ─────────────────────────────────────────────
# COG
# ─────────────────────────────────────────────
class PokerCog(commands.Cog, name="Poker"):
    """Texas Hold'em poker with chips."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.poker_games: dict = {}
        self.conn = bot.conn
        self.cursor = bot.cursor
        self._ensure_table()

    def _ensure_table(self):
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS poker_chips (
                user_id INTEGER PRIMARY KEY,
                chips INTEGER NOT NULL DEFAULT 1000,
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

    @app_commands.command(name="daily", description="Claim your daily poker chips")
    async def daily(self, interaction: discord.Interaction):
        self.ensure_chips(interaction.user.id)
        self.cursor.execute("SELECT last_daily FROM poker_chips WHERE user_id = ?", (interaction.user.id,))
        last_daily = self.cursor.fetchone()[0]
        now = int(time.time())
        if now - last_daily < 86400:
            remaining = 86400 - (now - last_daily)
            h, m = remaining // 3600, (remaining % 3600) // 60
            await interaction.response.send_message(f"⏳ Come back in **{h}h {m}m**.", ephemeral=True)
            return
        reward = random.randint(300, 700)
        self.add_chips(interaction.user.id, reward)
        self.cursor.execute(
            "UPDATE poker_chips SET last_daily = ? WHERE user_id = ?", (now, interaction.user.id)
        )
        self.conn.commit()
        total = self.get_chips(interaction.user.id)
        await interaction.response.send_message(f"💰 Claimed **{reward} chips**! Total: **{total}**.")

    @poker_group.command(name="create", description="Create a poker table")
    async def poker_create(self, interaction: discord.Interaction, buy_in: int = 100):
        channel_id = interaction.channel.id
        if channel_id in self.poker_games:
            await interaction.response.send_message("A game is already active here.", ephemeral=True)
            return
        self.poker_games[channel_id] = {
            "host": interaction.user.id,
            "buy_in": buy_in,
            "players": {},
            "deck": [],
            "community": [],
            "visible_community": [],
            "pot": 0,
            "phase": "waiting",
            "current_bet": 0,
            "player_order": [],
            "turn_index": 0,
        }
        await interaction.response.send_message(
            f"🃏 Poker table created! Buy-in: **{buy_in}** chips\nUse `/poker join` to join, then `/poker start` when ready."
        )

    @poker_group.command(name="join", description="Join the current poker table")
    async def poker_join(self, interaction: discord.Interaction):
        game = self.poker_games.get(interaction.channel.id)
        if not game or game["phase"] != "waiting":
            await interaction.response.send_message("No joinable table here.", ephemeral=True)
            return
        if interaction.user.id in game["players"]:
            await interaction.response.send_message("You're already in.", ephemeral=True)
            return
        buy_in = game["buy_in"]
        if not self.remove_chips(interaction.user.id, buy_in):
            await interaction.response.send_message(f"Not enough chips (need **{buy_in}**).", ephemeral=True)
            return
        game["players"][interaction.user.id] = {
            "cards": [], "folded": False, "bet": 0, "acted": False, "all_in": False
        }
        game["pot"] += buy_in
        await interaction.response.send_message(
            f"✅ {interaction.user.mention} joined! Pot: **{game['pot']}**"
        )

    @poker_group.command(name="chips", description="Check your chip balance")
    async def poker_chips(self, interaction: discord.Interaction):
        chips = self.get_chips(interaction.user.id)
        await interaction.response.send_message(f"💰 You have **{chips} chips**.", ephemeral=True)

    @poker_group.command(name="setchips", description="Add or remove chips (admin)")
    @app_commands.check(is_owner)
    async def poker_setchips(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        self.ensure_chips(user.id)
        self.cursor.execute(
            "UPDATE poker_chips SET chips = chips + ? WHERE user_id = ?", (amount, user.id)
        )
        self.conn.commit()
        total = self.get_chips(user.id)
        await interaction.response.send_message(
            f"💰 Updated {user.mention} by **{amount:+}**. Balance: **{total}**"
        )

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

        deck = build_deck()
        game["deck"] = deck
        game["community"] = [deck.pop() for _ in range(5)]
        game["visible_community"] = []
        game["phase"] = "preflop"
        game["current_bet"] = 0

        # 🔥 ACKNOWLEDGE FIRST
        await interaction.response.defer()

        # 🎴 DEAL CARDS
        for user_id, p in game["players"].items():
            p.update({
                "cards": [deck.pop(), deck.pop()],
                "folded": False, "bet": 0, "acted": False, "all_in": False,
            })

            try:
                member = await interaction.guild.fetch_member(user_id)
                await member.send(f"🃏 Your hole cards: **{' '.join(p['cards'])}**")
            except Exception:
                pass

        # 🎯 SET TURN
        game["player_order"] = list(game["players"].keys())
        game["turn_index"] = 0

        # 🃏 SEND GAME MESSAGE AFTER
        view = PokerBetView(interaction.channel.id, game, self)

        await interaction.followup.send(
            build_status(game),
            view=view
        )

    @poker_group.command(name="end", description="Force-end the current game (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def poker_end(self, interaction: discord.Interaction):
        if interaction.channel.id not in self.poker_games:
            await interaction.response.send_message("No active game here.", ephemeral=True)
            return
        del self.poker_games[interaction.channel.id]
        await interaction.response.send_message("🛑 Game ended.")


async def setup(bot: commands.Bot):
    await bot.add_cog(PokerCog(bot))