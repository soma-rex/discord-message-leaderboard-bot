
import asyncio
import random
import time
from collections import Counter
from itertools import combinations

import discord
from discord import app_commands
from discord.ext import commands

from .chips import ChipsMixin


CHIP_EMOJI = "<:poker_chip:1487837444685430896>"
SPADE_EMOJI = "<:spade:1487837442907050197>"
HEART_EMOJI = "<:heart:1487837441535508591>"
DIAM_EMOJI = "<:diamond:1487837439967105075>"
CLUB_EMOJI = "<:club:1487837438083862698>"

SUITS = ["S", "H", "D", "C"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
RANK_VALUE = {rank: index for index, rank in enumerate(RANKS, start=2)}
SUIT_SYMBOLS = {
    "S": SPADE_EMOJI,
    "H": HEART_EMOJI,
    "D": DIAM_EMOJI,
    "C": CLUB_EMOJI,
}
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
    "preflop": discord.Color.blurple(),
    "flop": discord.Color.blue(),
    "turn": discord.Color.orange(),
    "river": discord.Color.red(),
    "waiting": discord.Color.dark_grey(),
}
TABLE_PRESETS = {
    "high_rollers": {
        "name": "Dragon's Vault",
        "buy_in": 10000,
        "raise_cap": 5000,
    },
    "low_stakes": {
        "name": "Firefly Den",
        "buy_in": 1000,
        "raise_cap": 500,
    },
    "custom": {
        "name": "Nebula Syndicate",
        "buy_in": None,
        "raise_cap": None,
    },
}

TURN_TIMEOUT_SECONDS = 300
INACTIVITY_TIMEOUT_SECONDS = 1800
HAND_START_DELAY_SECONDS = 15


def is_owner(interaction: discord.Interaction) -> bool:
    return interaction.user.id == 720550790036455444


async def fetch_display_name(client: discord.Client, guild, user_id: int) -> str:
    member = guild.get_member(user_id) if guild else None
    if member:
        return member.display_name
    try:
        user = await client.fetch_user(user_id)
    except discord.DiscordException:
        return f"User {user_id}"
    return user.name


def build_deck() -> list[str]:
    deck = [f"{rank}{suit}" for suit in SUITS for rank in RANKS]
    random.shuffle(deck)
    return deck


def card_rank(card: str) -> str:
    return card[:-1]


def card_suit(card: str) -> str:
    return card[-1]


def format_card(card: str) -> str:
    rank = card_rank(card)
    suit = card_suit(card)
    return f"**{rank}**{SUIT_SYMBOLS.get(suit, suit)}"


def format_cards(cards: list[str]) -> str:
    return "  ".join(format_card(card) for card in cards)


def _score_five(cards: list[str]) -> tuple:
    ranks = [card_rank(card) for card in cards]
    suits = [card_suit(card) for card in cards]
    values = sorted([RANK_VALUE[rank] for rank in ranks], reverse=True)
    counts = Counter(ranks)
    frequency = sorted(counts.values(), reverse=True)

    is_flush = len(set(suits)) == 1
    is_straight = len(set(values)) == 5 and values[0] - values[-1] == 4
    if set(values) == {14, 2, 3, 4, 5}:
        is_straight = True
        values = [5, 4, 3, 2, 1]

    if is_straight and is_flush:
        return 8, values
    if frequency[0] == 4:
        quad_rank = next(rank for rank, count in counts.items() if count == 4)
        kickers = sorted([RANK_VALUE[rank] for rank in ranks if rank != quad_rank], reverse=True)
        return 7, [RANK_VALUE[quad_rank], *kickers]
    if frequency[0] == 3 and frequency[1] == 2:
        trip_rank = next(rank for rank, count in counts.items() if count == 3)
        pair_rank = next(rank for rank, count in counts.items() if count == 2)
        return 6, [RANK_VALUE[trip_rank], RANK_VALUE[pair_rank]]
    if is_flush:
        return 5, values
    if is_straight:
        return 4, values
    if frequency[0] == 3:
        trip_rank = next(rank for rank, count in counts.items() if count == 3)
        kickers = sorted([RANK_VALUE[rank] for rank, count in counts.items() if count == 1], reverse=True)
        return 3, [RANK_VALUE[trip_rank], *kickers]
    if frequency[0] == 2 and frequency[1] == 2:
        pair_ranks = sorted([RANK_VALUE[rank] for rank, count in counts.items() if count == 2], reverse=True)
        kicker = max(RANK_VALUE[rank] for rank, count in counts.items() if count == 1)
        return 2, [*pair_ranks, kicker]
    if frequency[0] == 2:
        pair_rank = next(rank for rank, count in counts.items() if count == 2)
        kickers = sorted([RANK_VALUE[rank] for rank, count in counts.items() if count == 1], reverse=True)
        return 1, [RANK_VALUE[pair_rank], *kickers]
    return 0, values


def evaluate_hand(cards: list[str]) -> tuple:
    if len(cards) <= 5:
        return _score_five(cards)
    return max(_score_five(list(combo)) for combo in combinations(cards, 5))


def hand_name(score: tuple) -> str:
    return HAND_NAMES.get(score[0], "Unknown")


def build_side_pots(game: dict) -> list[dict]:
    players = game["players"]
    contributions = {
        user_id: player["total_chip_in"]
        for user_id, player in players.items()
        if player["in_current_hand"] and player["total_chip_in"] > 0
    }
    pots = []
    while contributions:
        minimum = min(contributions.values())
        involved = list(contributions.keys())
        pot_amount = minimum * len(involved)
        eligible = [user_id for user_id in involved if not players[user_id]["folded"]]
        if eligible:
            pots.append({"amount": pot_amount, "eligible": eligible})
        contributions = {
            user_id: amount - minimum
            for user_id, amount in contributions.items()
            if amount - minimum > 0
        }
    return pots


def eligible_table_players(game: dict) -> list[int]:
    return [user_id for user_id in game["seating_order"] if game["players"][user_id]["stack"] > 0]


def blind_amounts(game: dict) -> tuple[int, int]:
    big_blind = max(20, game["buy_in"] // 50)
    small_blind = max(10, big_blind // 2)
    return small_blind, big_blind


def build_waiting_embed(game: dict) -> discord.Embed:
    raise_cap = game["raise_cap"]
    raise_cap_text = f"**{raise_cap}** {CHIP_EMOJI}" if raise_cap is not None else "**No cap**"
    next_round_text = ""
    next_hand_starts_at = game.get("next_hand_starts_at")
    if game["started"] and next_hand_starts_at:
        remaining = max(0, int(round(next_hand_starts_at - time.time())))
        next_round_text = f"\nNext round starts in **{remaining}s**."
    embed = discord.Embed(
        title=f"{SPADE_EMOJI} {HEART_EMOJI}  {game['table_name']}  {DIAM_EMOJI} {CLUB_EMOJI}",
        color=discord.Color.blurple(),
        description=(
            f"Buy-in: **{game['buy_in']}** {CHIP_EMOJI}\n"
            f"Raise cap: {raise_cap_text}\n\n"
            "Use `/poker join` or the Buy In button to buy into the table.\n"
            "Use `/poker start` once, then hands roll automatically until the table ends."
            f"{next_round_text}"
        ),
    )
    return embed


def build_game_embed(game: dict) -> discord.Embed:
    phase = game["phase"].title()
    current_uid = game["player_order"][game["turn_index"]]
    board = format_cards(game["visible_community"]) if game["visible_community"] else "*(cards hidden)*"
    embed = discord.Embed(
        title=f"{SPADE_EMOJI} {HEART_EMOJI}  Texas Hold'em  {DIAM_EMOJI} {CLUB_EMOJI}",
        color=PHASE_COLORS.get(game["phase"], discord.Color.blurple()),
    )
    embed.add_field(name="Table", value=game["table_name"], inline=True)
    embed.add_field(name="Hand", value=f"#{game['hand_number']}", inline=True)
    embed.add_field(name="Acting", value=f"<@{current_uid}>", inline=True)
    embed.add_field(name="Board", value=board, inline=False)
    embed.add_field(name="Pot", value=f"**{game['pot']}** {CHIP_EMOJI}", inline=True)
    embed.add_field(name="Current bet", value=f"**{game['current_bet']}**", inline=True)
    embed.add_field(name="Phase", value=phase, inline=True)
    embed.set_footer(text="Hands continue automatically. Press Players to see stacks and status.")
    return embed


def build_players_embed(game: dict) -> discord.Embed:
    embed = discord.Embed(title="Players at the table", color=discord.Color.dark_grey())
    current_uid = None
    if game["hand_active"] and game["player_order"]:
        current_uid = game["player_order"][game["turn_index"]]

    lines = []
    for user_id in game["seating_order"]:
        player = game["players"][user_id]
        stack_text = f"stack **{player['stack']}** {CHIP_EMOJI}"
        if player["stack"] <= 0:
            status = "busted"
        elif player.get("leaving_after_hand"):
            status = "leaving after this hand"
        elif not game["hand_active"]:
            status = "ready for next hand"
        elif not player["in_current_hand"]:
            status = "joins next hand"
        elif player["folded"]:
            status = "folded"
        elif player["all_in"]:
            status = "all-in"
        else:
            status = f"bet {player['bet']}"
        turn = "  <- their turn" if current_uid == user_id else ""
        lines.append(f"<@{user_id}> - {stack_text} - {status}{turn}")

    embed.description = "\n".join(lines) if lines else "No one is seated."
    return embed

class CustomTableModal(discord.ui.Modal, title="Nebula Syndicate"):
    buy_in = discord.ui.TextInput(
        label="Buy-in",
        placeholder="Enter the table buy-in",
        required=True,
        max_length=6,
    )
    raise_cap = discord.ui.TextInput(
        label="Raise cap",
        placeholder="Enter the max raise per turn",
        required=True,
        max_length=6,
    )

    def __init__(self, cog: "PokerCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        buy_in_raw = str(self.buy_in).strip()
        raise_cap_raw = str(self.raise_cap).strip()
        if not buy_in_raw.isdigit() or not raise_cap_raw.isdigit():
            await interaction.response.send_message("Buy-in and raise cap must be whole numbers.", ephemeral=True)
            return

        buy_in = int(buy_in_raw)
        raise_cap = int(raise_cap_raw)
        if buy_in <= 0 or raise_cap <= 0:
            await interaction.response.send_message("Buy-in and raise cap must be greater than 0.", ephemeral=True)
            return

        await self.cog._open_table(
            interaction,
            table_key="custom",
            table_name=TABLE_PRESETS["custom"]["name"],
            buy_in=buy_in,
            raise_cap=raise_cap,
        )


class RaiseModal(discord.ui.Modal, title="Custom Raise"):
    raise_amount = discord.ui.TextInput(
        label="Raise amount",
        placeholder="Raise by this amount",
        required=True,
        max_length=6,
    )

    def __init__(self, view: "PokerBetView"):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        game, player, error = self.view._guard(interaction)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        raw_amount = str(self.raise_amount).strip()
        if not raw_amount.isdigit():
            await interaction.response.send_message("Raise amount must be a whole number.", ephemeral=True)
            return

        raise_by = int(raw_amount)
        if raise_by <= 0:
            await interaction.response.send_message("Raise amount must be greater than 0.", ephemeral=True)
            return
        if game["raise_cap"] is not None and raise_by > game["raise_cap"]:
            await interaction.response.send_message(
                f"This table only allows raises up to **{game['raise_cap']}** per turn.",
                ephemeral=True,
            )
            return

        target = game["current_bet"] + raise_by
        amount = target - player["bet"]
        if amount <= 0:
            await interaction.response.send_message("Invalid raise amount.", ephemeral=True)
            return
        if player["stack"] < amount:
            await interaction.response.send_message("Not enough table chips. Try All-In.", ephemeral=True)
            return

        self.view.cog._touch_game(game)
        player["stack"] -= amount
        player["bet"] = target
        player["total_chip_in"] += amount
        game["pot"] += amount
        game["current_bet"] = target
        player["acted"] = True

        for user_id, other in game["players"].items():
            if user_id != interaction.user.id and other["in_current_hand"] and not other["folded"] and not other["all_in"]:
                other["acted"] = False

        self.view._advance_turn_index(game)
        await interaction.response.send_message(f"Raised by **{raise_by}** to **{target}**.", ephemeral=True)
        await self.view._announce_action(interaction.channel, interaction.user, f"raised by **{raise_by}** to **{target}**.")
        await self.view.resolve_turn(interaction.channel)


# ... (keeping all imports and earlier code the same until the PokerBetView class) ...

class PokerBetView(discord.ui.View):
    def __init__(self, channel_id: int, cog: "PokerCog", *, hand_number: int, expected_user_id: int):
        super().__init__(timeout=TURN_TIMEOUT_SECONDS)
        self.channel_id = channel_id
        self.cog = cog
        self.hand_number = hand_number
        self.expected_user_id = expected_user_id

    def get_game(self) -> dict | None:
        return self.cog.poker_games.get(self.channel_id)

    def _guard(self, interaction: discord.Interaction):
        game = self.get_game()
        if not game or not game["hand_active"]:
            return None, None, "No active hand."
        if game["hand_number"] != self.hand_number:
            return game, None, "That action prompt belongs to an older hand. Use the newest poker message."
        action_message = game.get("action_message")
        if action_message is not None and interaction.message is not None and interaction.message.id != action_message.id:
            return game, None, "That action prompt is out of date. Use the newest poker message."
        current_uid = game["player_order"][game["turn_index"]]
        if current_uid != self.expected_user_id:
            return game, None, "That action prompt is out of date. Use the newest poker message."
        if interaction.user.id != current_uid:
            return game, None, "It's not your turn."
        player = game["players"][interaction.user.id]
        if not player["in_current_hand"] or player["folded"]:
            return game, None, "You're not active in this hand."
        if player["all_in"]:
            return game, None, "You're already all-in."
        if player["acted"]:
            return game, None, "You already acted this street."
        return game, player, None

    def _advance_turn_index(self, game: dict) -> None:
        if not game["player_order"]:
            return
        total = len(game["player_order"])
        for offset in range(1, total + 1):
            next_index = (game["turn_index"] + offset) % total
            next_uid = game["player_order"][next_index]
            player = game["players"][next_uid]
            if player["in_current_hand"] and not player["folded"] and not player["all_in"]:
                game["turn_index"] = next_index
                return

    async def on_timeout(self):
        game = self.get_game()
        if not game or not game["hand_active"]:
            return
        if game["hand_number"] != self.hand_number:
            return

        current_uid = game["player_order"][game["turn_index"]]
        if current_uid != self.expected_user_id:
            return
        player = game["players"][current_uid]
        if not player["in_current_hand"] or player["folded"] or player["all_in"]:
            return

        player["folded"] = True
        player["acted"] = True
        self._advance_turn_index(game)
        self.cog._touch_game(game)

        channel = await self.cog._get_channel(self.channel_id)
        if channel is None:
            return

        await channel.send(
            embed=discord.Embed(
                description=f"<@{current_uid}> took too long and was auto-folded.",
                color=discord.Color.orange(),
            )
        )
        await self.resolve_turn(channel)

    async def _announce_action(self, channel: discord.TextChannel, user: discord.Member, action: str):
        """Send action announcement message."""
        await channel.send(
            embed=discord.Embed(
                description=f"**{user.display_name}** {action}",
                color=discord.Color.dark_grey(),
            )
        )

    async def _send_game_update(self, channel: discord.TextChannel, game: dict, next_user_id: int):
        """Send updated game embed with next player pinged."""
        view = PokerBetView(
            channel.id,
            self.cog,
            hand_number=game["hand_number"],
            expected_user_id=next_user_id,
        )

        message = await channel.send(
            f"<@{next_user_id}> Your turn!",
            embed=build_game_embed(game),
            view=view,
        )
        game["action_message"] = message

    async def advance_phase(self, channel: discord.TextChannel):
        game = self.get_game()
        if not game or not game["hand_active"]:
            return

        phases = ["preflop", "flop", "turn", "river", "showdown"]
        next_phase = phases[phases.index(game["phase"]) + 1]
        game["phase"] = next_phase
        self.cog._touch_game(game)

        if next_phase == "flop":
            game["visible_community"] = game["community"][:3]
        elif next_phase == "turn":
            game["visible_community"] = game["community"][:4]
        elif next_phase == "river":
            game["visible_community"] = game["community"][:5]
        elif next_phase == "showdown":
            await self.cog.finish_hand(channel, game)
            return

        game["current_bet"] = 0
        for player in game["players"].values():
            player["bet"] = 0
            if player["in_current_hand"] and not player["folded"] and not player["all_in"]:
                player["acted"] = False

        can_act = [
            user_id
            for user_id in game["player_order"]
            if game["players"][user_id]["in_current_hand"]
               and not game["players"][user_id]["folded"]
               and not game["players"][user_id]["all_in"]
        ]
        if len(can_act) <= 1:
            await self.advance_phase(channel)
            return

        game["turn_index"] = game["player_order"].index(can_act[0])
        await self._send_game_update(channel, game, can_act[0])

    async def resolve_turn(self, channel: discord.TextChannel):
        game = self.get_game()
        if not game or not game["hand_active"]:
            return

        alive = [
            user_id
            for user_id in game["player_order"]
            if game["players"][user_id]["in_current_hand"] and not game["players"][user_id]["folded"]
        ]
        if len(alive) == 1:
            winner_id = alive[0]
            game["players"][winner_id]["stack"] += game["pot"]
            winner_name = await self.cog._member_name(channel, winner_id)
            await channel.send(
                embed=discord.Embed(
                    title=f"{winner_name} wins the hand!",
                    description=f"Everyone else folded. **{game['pot']}** {CHIP_EMOJI} awarded.",
                    color=discord.Color.gold(),
                )
            )
            await self.cog.finish_hand(channel, game, showdown=False)
            return

        can_act_players = [
            game["players"][user_id]
            for user_id in game["player_order"]
            if game["players"][user_id]["in_current_hand"]
               and not game["players"][user_id]["folded"]
               and not game["players"][user_id]["all_in"]
        ]
        bets_level = all(
            player["bet"] == game["current_bet"] for player in can_act_players) if can_act_players else True
        all_acted = all(player["acted"] for player in can_act_players) if can_act_players else True

        if not can_act_players or (all_acted and bets_level):
            await self.advance_phase(channel)
            return

        current_uid = game["player_order"][game["turn_index"]]
        await self._send_game_update(channel, game, current_uid)

    @discord.ui.button(label="Fold", style=discord.ButtonStyle.danger, row=0)
    async def fold(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, player, error = self._guard(interaction)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        self.cog._touch_game(game)
        player["folded"] = True
        player["acted"] = True
        self._advance_turn_index(game)

        await interaction.response.send_message("You folded.", ephemeral=True)
        await self._announce_action(interaction.channel, interaction.user, "folded.")
        await self.resolve_turn(interaction.channel)

    @discord.ui.button(label="Check", style=discord.ButtonStyle.secondary, row=0)
    async def check(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, player, error = self._guard(interaction)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        if player["bet"] != game["current_bet"]:
            await interaction.response.send_message("You can't check while you're behind the current bet.",
                                                    ephemeral=True)
            return

        self.cog._touch_game(game)
        player["acted"] = True
        self._advance_turn_index(game)

        await interaction.response.send_message("Checked.", ephemeral=True)
        await self._announce_action(interaction.channel, interaction.user, "checked.")
        await self.resolve_turn(interaction.channel)

    @discord.ui.button(label="Call", style=discord.ButtonStyle.primary, row=0)
    async def call(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, player, error = self._guard(interaction)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        amount = game["current_bet"] - player["bet"]
        if amount <= 0:
            await interaction.response.send_message("Nothing to call. Use Check.", ephemeral=True)
            return

        self.cog._touch_game(game)
        if player["stack"] <= amount:
            amount = player["stack"]
            player["all_in"] = True

        player["stack"] -= amount
        player["bet"] += amount
        player["total_chip_in"] += amount
        game["pot"] += amount
        player["acted"] = True
        self._advance_turn_index(game)

        suffix = " and is now all-in" if player["all_in"] else ""
        await interaction.response.send_message(f"Called **{amount}**{suffix}.", ephemeral=True)
        await self._announce_action(interaction.channel, interaction.user, f"called **{amount}**{suffix}.")
        await self.resolve_turn(interaction.channel)

    @discord.ui.button(label="Raise", style=discord.ButtonStyle.success, row=1)
    async def raise_bet(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, player, error = self._guard(interaction)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.send_modal(RaiseModal(self))

    @discord.ui.button(label="All-In", style=discord.ButtonStyle.danger, row=1)
    async def all_in(self, interaction: discord.Interaction, button: discord.ui.Button):
        game, player, error = self._guard(interaction)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        if player["stack"] <= 0:
            await interaction.response.send_message("You have no chips left at the table.", ephemeral=True)
            return

        self.cog._touch_game(game)
        chips = player["stack"]
        player["stack"] = 0
        player["bet"] += chips
        player["total_chip_in"] += chips
        game["pot"] += chips
        player["all_in"] = True
        player["acted"] = True

        if player["bet"] > game["current_bet"]:
            game["current_bet"] = player["bet"]
            for user_id, other in game["players"].items():
                if user_id != interaction.user.id and other["in_current_hand"] and not other["folded"] and not other[
                    "all_in"]:
                    other["acted"] = False

        self._advance_turn_index(game)

        await interaction.response.send_message(
            f"All-in with **{chips}** chips. Your total bet is now **{player['bet']}**.",
            ephemeral=True,
        )
        await self._announce_action(
            interaction.channel,
            interaction.user,
            f"went all-in with **{chips}** chips. Total bet: **{player['bet']}**.",
        )
        await self.resolve_turn(interaction.channel)

    @discord.ui.button(label="Players", style=discord.ButtonStyle.secondary, row=1)
    async def show_players(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = self.get_game()
        if not game:
            await interaction.response.send_message("No active table.", ephemeral=True)
            return
        await interaction.response.send_message(embed=build_players_embed(game), ephemeral=True)

    @discord.ui.button(label="My Cards", style=discord.ButtonStyle.primary, row=2)
    async def show_cards(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_player_cards(interaction)

    @discord.ui.button(label="Leave Match", style=discord.ButtonStyle.secondary, row=2)
    async def leave_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.leave_table(interaction)


# ... (rest of the code remains the same - RaiseModal, PokerTableView, and PokerCog) ...


class PokerCog(commands.Cog, ChipsMixin, name="Poker"):
    """Texas Hold'em poker tables that continue until the table ends."""

    poker_group = app_commands.Group(name="poker", description="Texas Hold'em with chips")
    leaderboard_group = app_commands.Group(name="leaderboard", description="Leaderboard commands")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.poker_games: dict[int, dict] = {}
        self.conn = bot.conn
        self.cursor = bot.cursor
        self._ensure_chip_table()

    def cog_unload(self):
        for game in self.poker_games.values():
            inactivity_task = game.get("inactivity_task")
            if inactivity_task:
                inactivity_task.cancel()
            pending_start_task = game.get("pending_start_task")
            if pending_start_task:
                pending_start_task.cancel()

    def _ensure_table(self):
        self._ensure_chip_table()

    def _touch_game(self, game: dict) -> None:
        game["last_activity"] = time.time()

    def _create_player_state(self, stack: int) -> dict:
        return {
            "stack": stack,
            "cards": [],
            "folded": False,
            "bet": 0,
            "acted": False,
            "total_chip_in": 0,
            "all_in": False,
            "in_current_hand": False,
            "leaving_after_hand": False,
        }

    def _post_forced_bet(self, game: dict, user_id: int, amount: int) -> int:
        player = game["players"][user_id]
        posted = min(amount, player["stack"])
        if posted <= 0:
            return 0
        player["stack"] -= posted
        player["bet"] += posted
        player["total_chip_in"] += posted
        game["pot"] += posted
        if player["stack"] == 0:
            player["all_in"] = True
        return posted

    async def _get_channel(self, channel_id: int):
        channel = self.bot.get_channel(channel_id)
        if channel is not None:
            return channel
        try:
            return await self.bot.fetch_channel(channel_id)
        except Exception:
            return None

    async def buy_in_player(self, interaction: discord.Interaction) -> None:
        game = self.poker_games.get(interaction.channel.id)
        if not game:
            await interaction.response.send_message("No poker table exists here.", ephemeral=True)
            return

        player = game["players"].get(interaction.user.id)
        if player and player["stack"] > 0:
            await interaction.response.send_message("You're already seated with chips at this table.", ephemeral=True)
            return

        buy_in = game["buy_in"]
        if not self.remove_chips(interaction.user.id, buy_in):
            await interaction.response.send_message(f"You need **{buy_in}** {CHIP_EMOJI} to buy in.", ephemeral=True)
            return

        if player:
            player["stack"] += buy_in
            player["leaving_after_hand"] = False
        else:
            game["players"][interaction.user.id] = self._create_player_state(buy_in)
            game["seating_order"].append(interaction.user.id)

        self._touch_game(game)
        status = "will join the next hand" if game["hand_active"] else "is ready to play"
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"{interaction.user.mention} bought in for **{buy_in}** {CHIP_EMOJI} and {status}.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )
        await interaction.channel.send(
            embed=discord.Embed(
                description=f"{interaction.user.mention} bought in for **{buy_in}** {CHIP_EMOJI} and {status}.",
                color=discord.Color.green(),
            ),
            view=PokerTableView(interaction.channel.id, self),
        )

        if game["started"] and not game["hand_active"] and len(eligible_table_players(game)) >= 2:
            await self._queue_next_hand(interaction.channel.id, delay=HAND_START_DELAY_SECONDS)

    async def show_player_cards(self, interaction: discord.Interaction) -> None:
        game = self.poker_games.get(interaction.channel.id)
        if not game or not game["hand_active"]:
            await interaction.response.send_message("No hand is active right now.", ephemeral=True)
            return

        player = game["players"].get(interaction.user.id)
        if not player or not player["in_current_hand"] or not player["cards"]:
            await interaction.response.send_message("You're not in the current hand.", ephemeral=True)
            return

        embed = discord.Embed(title="Your Cards", color=discord.Color.blurple())
        embed.add_field(name="Hole cards", value=format_cards(player["cards"]), inline=False)
        embed.add_field(name="Board", value=format_cards(game["visible_community"]) or "*(cards hidden)*", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _member_name(self, channel: discord.TextChannel, user_id: int) -> str:
        try:
            member = await channel.guild.fetch_member(user_id)
            return member.display_name
        except Exception:
            return f"User {user_id}"

    async def _monitor_inactivity(self, channel_id: int):
        while True:
            await asyncio.sleep(60)
            game = self.poker_games.get(channel_id)
            if not game or game["ending"]:
                return
            if time.time() - game["last_activity"] < INACTIVITY_TIMEOUT_SECONDS:
                continue
            await self._close_table(channel_id, "Table closed after 30 minutes with no hands or actions.")
            return

    def _cancel_pending_start(self, game: dict) -> None:
        task = game.get("pending_start_task")
        current_task = asyncio.current_task()
        if task and task is not current_task:
            task.cancel()
        game["pending_start_task"] = None
        game["next_hand_starts_at"] = None

    def _remove_player_from_table(self, game: dict, user_id: int) -> None:
        game["players"].pop(user_id, None)
        if user_id in game["seating_order"]:
            game["seating_order"].remove(user_id)
        if user_id in game["player_order"]:
            removed_index = game["player_order"].index(user_id)
            game["player_order"].remove(user_id)
            if game["player_order"]:
                if removed_index < game["turn_index"]:
                    game["turn_index"] -= 1
                game["turn_index"] %= len(game["player_order"])
            else:
                game["turn_index"] = 0

    async def _finalize_pending_leaves(self, channel, game: dict) -> None:
        departures = []
        for user_id in list(game["seating_order"]):
            player = game["players"].get(user_id)
            if not player or not player.get("leaving_after_hand"):
                continue
            refund = player["stack"]
            if refund > 0:
                self.add_chips(user_id, refund)
            departures.append((user_id, refund))
            self._remove_player_from_table(game, user_id)

        if departures and channel is not None:
            lines = []
            for user_id, refund in departures:
                refund_text = f" and was refunded **{refund}** {CHIP_EMOJI}" if refund > 0 else ""
                lines.append(f"<@{user_id}> left the table{refund_text}.")
            await channel.send(
                embed=discord.Embed(
                    title="Player left the table",
                    description="\n".join(lines),
                    color=discord.Color.orange(),
                )
            )

    async def _disable_action_view(self, game: dict) -> None:
        message = game.get("action_message")
        if message is None:
            return
        try:
            await message.edit(view=None)
        except Exception:
            pass
        game["action_message"] = None

    async def _send_turn_prompt(self, channel: discord.TextChannel, game: dict, mention_user_id: int) -> None:
        current_message = game.get("action_message")
        view = PokerBetView(
            channel.id,
            self,
            hand_number=game["hand_number"],
            expected_user_id=mention_user_id,
        )
        if current_message is not None:
            try:
                await current_message.edit(
                    content=f"<@{mention_user_id}>",
                    embed=build_game_embed(game),
                    view=view,
                )
                return
            except Exception:
                game["action_message"] = None

        message = await channel.send(
            f"<@{mention_user_id}>",
            embed=build_game_embed(game),
            view=view,
        )
        game["action_message"] = message

    async def _cash_out_round_players(self, channel: discord.TextChannel, game: dict) -> None:
        refunds = []
        for user_id in list(game["seating_order"]):
            player = game["players"].get(user_id)
            if not player:
                continue
            refund = player["stack"]
            if refund > 0:
                self.add_chips(user_id, refund)
            refunds.append((user_id, refund))
            self._remove_player_from_table(game, user_id)

        if refunds:
            lines = [f"<@{user_id}> cashed out **{amount}** {CHIP_EMOJI}" for user_id, amount in refunds]
            lines.append("Buy in again with `/poker join` or the Buy In button to play the next round.")
            await channel.send(
                embed=discord.Embed(
                    title="Round complete",
                    description="\n".join(lines),
                    color=discord.Color.blurple(),
                ),
                view=PokerTableView(channel.id, self),
            )

    async def _queue_next_hand(self, channel_id: int, delay: int = HAND_START_DELAY_SECONDS) -> None:
        game = self.poker_games.get(channel_id)
        if not game or game["ending"] or not game["started"] or game["hand_active"]:
            return
        if len(eligible_table_players(game)) < 2:
            return
        if game.get("pending_start_task"):
            return
        game["next_hand_starts_at"] = time.time() + delay

        channel = await self._get_channel(channel_id)
        if channel is not None:
            await channel.send(
                embed=discord.Embed(
                    title="Next round queued",
                    description=f"The next round starts in **{delay}s**.",
                    color=discord.Color.blurple(),
                ),
                view=PokerTableView(channel_id, self),
            )

        async def delayed_start():
            try:
                await asyncio.sleep(delay)
                await self._start_next_hand(channel_id)
            except asyncio.CancelledError:
                return
            finally:
                latest = self.poker_games.get(channel_id)
                if latest:
                    latest["pending_start_task"] = None

        game["pending_start_task"] = asyncio.create_task(delayed_start())

    def _reset_hand_state(self, game: dict) -> None:
        game["deck"] = []
        game["community"] = []
        game["visible_community"] = []
        game["pot"] = 0
        game["phase"] = "waiting"
        game["current_bet"] = 0
        game["player_order"] = []
        game["turn_index"] = 0
        game["hand_active"] = False
        for player in game["players"].values():
            player["cards"] = []
            player["folded"] = False
            player["bet"] = 0
            player["acted"] = False
            player["total_chip_in"] = 0
            player["all_in"] = False
            player["in_current_hand"] = False

    def _restore_hand_contributions(self, game: dict) -> None:
        if not game["hand_active"]:
            return
        for player in game["players"].values():
            if player["total_chip_in"] > 0:
                player["stack"] += player["total_chip_in"]
        self._reset_hand_state(game)

    async def _close_table(self, channel_id: int, reason: str, *, champion_id: int | None = None) -> None:
        game = self.poker_games.get(channel_id)
        if not game or game["ending"]:
            return

        game["ending"] = True
        self._touch_game(game)
        self._cancel_pending_start(game)

        inactivity_task = game.get("inactivity_task")
        if inactivity_task:
            inactivity_task.cancel()

        if game["hand_active"]:
            self._restore_hand_contributions(game)

        await self._disable_action_view(game)

        channel = await self._get_channel(channel_id)
        refunds = []
        for user_id, player in game["players"].items():
            if player["stack"] > 0:
                self.add_chips(user_id, player["stack"])
                refunds.append((user_id, player["stack"]))
                player["stack"] = 0

        del self.poker_games[channel_id]

        if channel is None:
            return

        description_lines = [reason]
        if champion_id is not None:
            champion_name = await self._member_name(channel, champion_id)
            description_lines.append(f"Winner: **{champion_name}**")
        if refunds:
            refund_lines = [f"<@{user_id}> refunded **{amount}** {CHIP_EMOJI}" for user_id, amount in refunds[:10]]
            description_lines.append("\n".join(refund_lines))

        await channel.send(
            embed=discord.Embed(
                title="Poker table ended",
                description="\n\n".join(description_lines),
                color=discord.Color.red(),
            )
        )

    async def _open_table(
        self,
        interaction: discord.Interaction,
        *,
        table_key: str,
        table_name: str,
        buy_in: int,
        raise_cap: int | None,
    ):
        channel_id = interaction.channel.id
        if channel_id in self.poker_games:
            await interaction.response.send_message("A poker table is already active here.", ephemeral=True)
            return

        game = {
            "host": interaction.user.id,
            "table_key": table_key,
            "table_name": table_name,
            "buy_in": buy_in,
            "raise_cap": raise_cap,
            "players": {},
            "seating_order": [],
            "player_order": [],
            "turn_index": 0,
            "deck": [],
            "community": [],
            "visible_community": [],
            "pot": 0,
            "phase": "waiting",
            "current_bet": 0,
            "started": False,
            "hand_active": False,
            "hand_number": 0,
            "dealer_index": -1,
            "last_activity": time.time(),
            "ending": False,
            "pending_start_task": None,
            "next_hand_starts_at": None,
            "action_message": None,
            "inactivity_task": None,
        }
        game["inactivity_task"] = asyncio.create_task(self._monitor_inactivity(channel_id))
        self.poker_games[channel_id] = game

        await interaction.response.send_message(embed=build_waiting_embed(game), view=PokerTableView(channel_id, self))

    async def _start_next_hand(self, channel_id: int) -> None:
        game = self.poker_games.get(channel_id)
        if not game or game["ending"] or not game["started"] or game["hand_active"]:
            return

        channel = await self._get_channel(channel_id)
        if channel is None:
            return

        await self._finalize_pending_leaves(channel, game)

        eligible = eligible_table_players(game)
        if len(eligible) == 0:
            await channel.send(
                embed=discord.Embed(
                    title="Waiting for players",
                    description="At least 2 players need to buy in before the next round can start.",
                    color=discord.Color.orange(),
                ),
                view=PokerTableView(channel_id, self),
            )
            return
        if len(eligible) == 1:
            await channel.send(
                embed=discord.Embed(
                    title="Waiting for one more player",
                    description="One more player needs to buy in before the next round can start.",
                    color=discord.Color.orange(),
                ),
                view=PokerTableView(channel_id, self),
            )
            return

        self._touch_game(game)
        self._cancel_pending_start(game)
        self._reset_hand_state(game)

        game["hand_number"] += 1
        game["hand_active"] = True
        game["phase"] = "preflop"
        game["deck"] = build_deck()
        game["community"] = [game["deck"].pop() for _ in range(5)]

        if game["seating_order"]:
            game["dealer_index"] = (game["dealer_index"] + 1) % len(game["seating_order"])

        ordered = []
        if game["seating_order"]:
            start = game["dealer_index"]
            for offset in range(len(game["seating_order"])):
                user_id = game["seating_order"][(start + offset) % len(game["seating_order"])]
                if user_id in eligible:
                    ordered.append(user_id)

        game["player_order"] = ordered
        game["turn_index"] = 0

        for user_id in game["player_order"]:
            player = game["players"][user_id]
            player["cards"] = [game["deck"].pop(), game["deck"].pop()]
            player["folded"] = False
            player["bet"] = 0
            player["acted"] = False
            player["total_chip_in"] = 0
            player["all_in"] = False
            player["in_current_hand"] = True
            player["leaving_after_hand"] = False

        blind_lines = []
        if len(game["player_order"]) >= 2:
            small_blind, big_blind = blind_amounts(game)
            small_blind_uid = game["player_order"][0]
            big_blind_uid = game["player_order"][1]
            posted_small = self._post_forced_bet(game, small_blind_uid, small_blind)
            posted_big = self._post_forced_bet(game, big_blind_uid, big_blind)
            game["current_bet"] = max(posted_small, posted_big)

            if len(game["player_order"]) == 2:
                game["turn_index"] = 0
            else:
                game["turn_index"] = 2

            blind_lines.append(f"<@{small_blind_uid}> posted the small blind of **{posted_small}**.")
            blind_lines.append(f"<@{big_blind_uid}> posted the big blind of **{posted_big}**.")

        current_uid = game["player_order"][game["turn_index"]]
        intro_lines = [f"Hand **#{game['hand_number']}** is starting. <@{current_uid}> acts first."]
        intro_lines.extend(blind_lines)
        await channel.send("\n".join(intro_lines))
        await self._send_turn_prompt(channel, game, current_uid)

    async def finish_hand(self, channel: discord.TextChannel, game: dict, *, showdown: bool = True) -> None:
        self._touch_game(game)
        if showdown:
            game["visible_community"] = game["community"][:]
            pots = build_side_pots(game)
            results_lines = []
            total_awarded = 0

            for index, pot in enumerate(pots, start=1):
                eligible = pot["eligible"]
                scored = []
                for user_id in eligible:
                    player = game["players"][user_id]
                    scored.append((evaluate_hand(player["cards"] + game["community"]), user_id))

                scored.sort(key=lambda item: item[0], reverse=True)
                best_score = scored[0][0]
                winners = [item for item in scored if item[0] == best_score]
                split = pot["amount"] // len(winners)
                remainder = pot["amount"] % len(winners)
                winner_names = []

                for winner_index, (_, winner_id) in enumerate(winners):
                    award = split + (remainder if winner_index == 0 else 0)
                    game["players"][winner_id]["stack"] += award
                    total_awarded += award
                    winner_names.append(await self._member_name(channel, winner_id))

                label = "Main pot" if index == 1 else f"Side pot {index - 1}"
                results_lines.append(f"**{label} ({pot['amount']})** -> {', '.join(winner_names)}")

            if total_awarded < game["pot"] and pots and pots[0]["eligible"]:
                fallback_winner = pots[0]["eligible"][0]
                game["players"][fallback_winner]["stack"] += game["pot"] - total_awarded

            hand_lines = []
            for user_id in game["player_order"]:
                player = game["players"][user_id]
                if player["folded"]:
                    continue
                score = evaluate_hand(player["cards"] + game["community"])
                hand_lines.append(
                    f"**{await self._member_name(channel, user_id)}** - {format_cards(player['cards'])} - *{hand_name(score)}*"
                )

            embed = discord.Embed(title="Showdown!", color=discord.Color.gold())
            embed.add_field(name="Board", value=format_cards(game["community"]) or "-", inline=False)
            embed.add_field(name="Results", value="\n".join(results_lines) or "-", inline=False)
            embed.add_field(name="Hands", value="\n".join(hand_lines) or "-", inline=False)
            await channel.send(embed=embed)

        await self._disable_action_view(game)
        self._reset_hand_state(game)
        await self._cash_out_round_players(channel, game)
        await self._finalize_pending_leaves(channel, game)
        await self._queue_next_hand(channel.id)

    async def leave_table(self, interaction: discord.Interaction) -> None:
        game = self.poker_games.get(interaction.channel.id)
        if not game:
            await interaction.response.send_message("No active table here.", ephemeral=True)
            return

        player = game["players"].get(interaction.user.id)
        if not player:
            await interaction.response.send_message("You're not seated at this table.", ephemeral=True)
            return

        self._touch_game(game)
        if game["hand_active"] and player["in_current_hand"]:
            player["leaving_after_hand"] = True
            await interaction.response.send_message(
                "You'll leave the match when this hand ends. Your remaining stack will be refunded then.",
                ephemeral=True,
            )
            return

        refund = player["stack"]
        if refund > 0:
            self.add_chips(interaction.user.id, refund)
        self._remove_player_from_table(game, interaction.user.id)
        await interaction.response.send_message(
            f"You left the match and were refunded **{refund}** {CHIP_EMOJI}.",
            ephemeral=True,
        )
        await interaction.channel.send(
            embed=discord.Embed(
                description=f"{interaction.user.mention} left the table and was refunded **{refund}** {CHIP_EMOJI}.",
                color=discord.Color.orange(),
            ),
            view=PokerTableView(interaction.channel.id, self),
        )

        if not game["hand_active"] and game["started"]:
            if len(eligible_table_players(game)) < 2:
                self._cancel_pending_start(game)

    @app_commands.command(name="daily", description="Claim your daily poker chips")
    async def daily(self, interaction: discord.Interaction):
        self.ensure_chips(interaction.user.id)
        self.cursor.execute("SELECT last_daily FROM poker_chips WHERE user_id = ?", (interaction.user.id,))
        last_daily = self.cursor.fetchone()[0]
        now = int(time.time())

        if now - last_daily < 86400:
            remaining = 86400 - (now - last_daily)
            hours, minutes = remaining // 3600, (remaining % 3600) // 60
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Daily not ready",
                    description=f"Come back in **{hours}h {minutes}m**.",
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        reward = random.randint(300, 700)
        self.add_chips(interaction.user.id, reward)
        self.cursor.execute("UPDATE poker_chips SET last_daily = ? WHERE user_id = ?", (now, interaction.user.id))
        self.conn.commit()

        total = self.get_chips(interaction.user.id)
        embed = discord.Embed(title="Daily reward claimed!", color=discord.Color.green())
        embed.add_field(name="Reward", value=f"**+{reward}** {CHIP_EMOJI}", inline=True)
        embed.add_field(name="Balance", value=f"**{total}** {CHIP_EMOJI}", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="chips", description="Check your chip balance")
    async def poker_chips(self, interaction: discord.Interaction):
        chips = self.get_chips(interaction.user.id)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Chip Balance",
                description=f"**{chips:,}** {CHIP_EMOJI}",
                color=discord.Color.gold(),
            )
        )

    @leaderboard_group.command(name="chips", description="Show the richest chip balances")
    async def chips_leaderboard(self, interaction: discord.Interaction):
        self.cursor.execute("SELECT user_id, chips FROM poker_chips ORDER BY chips DESC LIMIT 10")
        leaders = self.cursor.fetchall()
        if not leaders:
            await interaction.response.send_message("No chip data yet.", ephemeral=True)
            return

        self.ensure_chips(interaction.user.id)
        self.cursor.execute("SELECT COUNT(*) FROM poker_chips WHERE chips > ?", (self.get_chips(interaction.user.id),))
        higher_count = self.cursor.fetchone()[0]
        user_rank = higher_count + 1

        medals = [
            "<a:first:1479896994293219418>",
            "<a:second:1479896996331524229>",
            "<a:third:1480093491332780072>",
        ]
        lines = []
        for index, (user_id, chips) in enumerate(leaders, start=1):
            name = await fetch_display_name(self.bot, interaction.guild, user_id)
            icon = medals[index - 1] if index <= 3 else "-"
            lines.append(f"{icon} **{name}** - `{chips:,}` {CHIP_EMOJI}")

        embed = discord.Embed(
            title="<:pandatrophy:1479896789393084580> Chip Leaderboard",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"Your Rank: #{user_rank} | Your Balance: {self.get_chips(interaction.user.id):,}")
        await interaction.response.send_message(embed=embed)

    @poker_group.command(name="create", description="Create a poker table")
    @app_commands.describe(table="Choose which table to open")
    @app_commands.choices(
        table=[
            app_commands.Choice(name="Dragon's Vault (10,000 buy-in, 5,000 max raise)", value="high_rollers"),
            app_commands.Choice(name="Firefly Den (1,000 buy-in, 500 max raise)", value="low_stakes"),
            app_commands.Choice(name="Nebula Syndicate (custom buy-in, raise cap)", value="custom"),
        ]
    )
    async def poker_create(self, interaction: discord.Interaction, table: app_commands.Choice[str]):
        preset = TABLE_PRESETS[table.value]
        if table.value == "custom":
            await interaction.response.send_modal(CustomTableModal(self))
            return

        await self._open_table(
            interaction,
            table_key=table.value,
            table_name=preset["name"],
            buy_in=preset["buy_in"],
            raise_cap=preset["raise_cap"],
        )

    @poker_group.command(name="join", description="Buy into the current poker table")
    async def poker_join(self, interaction: discord.Interaction):
        await self.buy_in_player(interaction)

    @poker_group.command(name="start", description="Start the endless poker table (host only)")
    async def poker_start(self, interaction: discord.Interaction):
        game = self.poker_games.get(interaction.channel.id)
        if not game:
            await interaction.response.send_message("No table here.", ephemeral=True)
            return
        if interaction.user.id != game["host"]:
            await interaction.response.send_message("Only the table host can start it.", ephemeral=True)
            return
        if game["started"]:
            await interaction.response.send_message("This poker table is already running.", ephemeral=True)
            return
        if len(eligible_table_players(game)) < 2:
            await interaction.response.send_message(
                "You need at least 2 seated players with chips before the match can start.",
                ephemeral=True,
            )
            return

        game["started"] = True
        self._touch_game(game)
        await interaction.response.send_message("Poker table started. First round is starting now.")
        await self._start_next_hand(interaction.channel.id)

    @poker_group.command(name="setchips", description="Add or remove chips (owner only)")
    @app_commands.check(is_owner)
    async def poker_setchips(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        self.ensure_chips(user.id)
        self.cursor.execute("UPDATE poker_chips SET chips = chips + ? WHERE user_id = ?", (amount, user.id))
        self.conn.commit()
        total = self.get_chips(user.id)
        embed = discord.Embed(
            title="Chips updated",
            color=discord.Color.green() if amount >= 0 else discord.Color.red(),
        )
        embed.add_field(name="Player", value=user.mention, inline=True)
        embed.add_field(name="Change", value=f"**{amount:+}**", inline=True)
        embed.add_field(name="New balance", value=f"**{total:,}** {CHIP_EMOJI}", inline=True)
        await interaction.response.send_message(embed=embed)

    @poker_group.command(name="end", description="Force-end the current poker table")
    @app_commands.checks.has_permissions(administrator=True)
    async def poker_end(self, interaction: discord.Interaction):
        if interaction.channel.id not in self.poker_games:
            await interaction.response.send_message("No active poker table here.", ephemeral=True)
            return
        await interaction.response.send_message("Ending the poker table and refunding remaining table stacks.")
        await self._close_table(interaction.channel.id, "The poker table was ended by an admin.")


async def setup(bot: commands.Bot):
    await bot.add_cog(PokerCog(bot))
