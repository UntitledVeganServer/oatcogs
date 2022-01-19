from redbot.core import commands
from redbot.core import Config, bank
from redbot.core import checks
from redbot.core.utils.predicates import MessagePredicate
from redbot.core.data_manager import bundled_data_path
from io import BytesIO
import asyncio
import discord.utils 
import discord.ext
import discord
import random
import typing
import os
import re

try:
    from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageOps
    from PIL import features as pil_features
except Exception as e:
    raise RuntimeError(f"Can't load pillow: {e}\nDo '[p]pipinstall pillow'.")

class Wordle(commands.Cog):
    """Wordle -- now in Discord!"""

    default_guild_settings = {"WIN_AMOUNT": 500,
                              "TIME_LIMIT": 300,
                              "MULTIPLIER": True,
                              "STREAKS": True,
                              "TURN_MULTIPLIER": True,
                              "AWARD_ON_LOSS": False}

    default_member_settings = {"played": 0,
                               "total_wins": 0,
                               "total_earnings": 0,
                               "streak": 0,
                               "max_streak": 0,
                               "guess_distribution": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6": 0},
                               "green_letters": 0,
                               "yellow_letters": 0,
                               "total_lines": 0}

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier = 8234834580, force_registration=True)
        self.config.register_global(is_global = False)
        self.config.register_guild(**self.default_guild_settings)
        self.config.register_member(**self.default_member_settings)
        self.config.register_user(**self.default_member_settings)


    @commands.command()
    @commands.max_concurrency(1, per = commands.BucketType.member, wait = False)
    @commands.guild_only()
    async def wordle(self, ctx, guess = None):
        f"Play a game of Wordle!"
        target_word = await self.get_word()

        re.sub(r'\W+', '', target_word)

        guesses = []

        conf = await self.config

        if conf.is_global():
            member = conf.user(ctx.author)
        else:
            member = conf.member(ctx.author)

        guild = conf.guild(ctx.guild)

        member.played.set(member.played() + 1)

        wordle_image = await self.combine(await self.canvas(ctx, target_word, guesses), await self.keyboard(ctx, target_word, guesses))
        wordle_file = discord.File(wordle_image, filename = "wordle.png")

        message = await ctx.send("Welcome to Wordle! Type a five letter word to start. Type `stop` at any time to cancel the game.", file = wordle_file)

        while len(guesses) < 6 and target_word not in guesses:
            try:
                guess = await self.bot.wait_for("message", check = MessagePredicate.same_context(ctx), timeout = guild.TIME_LIMIT())
            except asyncio.TimeoutError:
                summary_text = "You didn't make a guess within the time limit."
                break
            else:
                if guess.content.lower() == "stop":
                    summary_text = "You stopped the game before you reached the end."
                    try:
                        await guess.delete()
                    except:
                        pass
                    break
                elif (len(guess.content) != 5):
                    await ctx.send("Your guess must be exactly 5 characters long.", delete_after = 4.0)
                elif guess.content.lower() not in open(f"{bundled_data_path(self)}/valid_guesses.txt").read() and guess.content.lower() not in open(f"{bundled_data_path(self)}/words.txt").read():
                    await ctx.send("That doesn't seem to be a valid word. Please guess again.", delete_after = 4.0)
                else:
                    guesses.append(guess.content.lower())

                    wordle_image = await self.combine(await self.canvas(ctx, target_word, guesses), await self.keyboard(ctx, target_word, guesses))
                    wordle_file = discord.File(wordle_image, filename = "wordle.png")

                    try:
                        await message.delete()
                    except:
                        pass

                    message = await ctx.send(file = wordle_file)

                    try:
                        await guess.delete()
                    except:
                        pass

        if target_word not in guesses:
            member.streak.set(0)

            if guild.AWARD_ON_LOSS:
                win_amount = 50 * len(guesses)
                multiplier = 1
            else:
                win_amount = 0
                multiplier = 0
        else:
            base_amount = guild.WIN_AMOUNT()
            streak = member.streak() + 1
            total_wins = member.total_wins() + 1
            max_streak = member.max_streak()

            member.total_wins.set(total_wins)
            member.streak.set(streak)

            async with member.guess_distribution() as guess_distribution:
                guess_distribution[str(len(guesses))] += 1

            if streak > max_streak:
                await member.max_streak.set(streak)

            if await member.MULTIPLIER():
                multiplier = 0
                if guild.STREAKS():
                    await member.streak.set(streak)
                    multiplier += (0.5 * (streak))
                if guild.TURN_MULTIPLIER():
                    multiplier += (1 / (len(guesses) / 6))
            else:
                multiplier = 1

            win_amount = base_amount * multiplier

        total_earnings = member.total_earnings()
        total_lines = member.total_lines() + len(guesses)
        member.total_lines.set(total_lines)

        try:
            await bank.deposit_credits(ctx.author, int(win_amount))
        except:
            pass
        else:
            await member.total_earnings.set(total_earnings + win_amount)

        try:
            await message.delete()
        except:
            pass

        summary_image = await self.combine(await self.canvas(target_word, guesses), await self.profile(ctx.author, target_word, guesses, win_amount, multiplier))
        summary_file = discord.File(summary_image, filename = "summary.png")
        await ctx.send(content = summary_text if summary_text else None, file = summary_file)

        return

    @commands.command()
    @commands.guild_only()
    async def wordlestats(self, ctx, member: discord.Member = None):
        if member is None:
            member = ctx.author

        profile_image = await self.save_image(await self.profile(ctx, member))
        profile_file = discord.File(profile_image, filename = "profile.png")
        await ctx.send(file = profile_file)

    async def get_word(self):
        return random.choice(open(f"{bundled_data_path(self)}/words.txt").read().splitlines()).lower()

    async def canvas(self, target_word, guesses):
        canvas_width = 350
        canvas_height = 420
        canvas_padding = 10

        cell_border_width = 2
        cell_gap = 5
        cell_width = 62
        cell_height = 62
        cell_row_count = 6
        cell_column_count = 5

        cell_bg = (0, 0, 0, 0)
        cell_white = (255, 255, 255, 255)
        cell_border = (121, 112, 99, 255)
        cell_default = (18, 18, 19, 255)
        cell_grey = (44, 48, 50, 255)
        cell_yellow = (145, 127, 47, 255)
        cell_green = (66, 113, 62, 255)
        cell_discord_dark = (41, 43, 47, 255)
        cell_discord_grey = (47, 49, 54, 255)

        text_color = (208, 204, 198, 255)

        HelveticaNeueBold = f"{bundled_data_path(self)}/HelveticaNeueBold.ttf"
        bold = ImageFont.truetype(HelveticaNeueBold, 32)

        canvas = Image.new("RGBA", (canvas_width, canvas_height), cell_bg)
        frame = ImageDraw.Draw(canvas)

        cell_rows = [list(target_word) for row in range(cell_row_count)]

        for y, cell_row in enumerate(cell_rows):
            answer = target_word

            for x, letter in enumerate(cell_row):
                start_x = canvas_padding + (cell_width * x) + (cell_gap * x)
                start_y = canvas_padding + (cell_height * y) + (cell_gap * y)
                end_x = start_x + cell_width
                end_y = start_y + cell_height

                font_x = start_x + (cell_width / 2)
                font_y = start_y + (cell_height / 2)

                frame.rectangle([(start_x, start_y), (end_x, end_y)], cell_bg, cell_white, cell_border_width)

                if y < len(guesses):
                    frame.rectangle([(start_x, start_y), (end_x, end_y)], cell_grey)
                    if guesses[y][x] == letter:
                        answer = ''.join(answer.split(letter, 1))
                        frame.rectangle([(start_x, start_y), (end_x, end_y)], cell_green)
                    frame.text(xy = (font_x, font_y), text = guesses[y][x].upper(), fill = text_color, font = bold, anchor = "mm")

            for x, letter in enumerate(cell_row):
                start_x = canvas_padding + (cell_width * x) + (cell_gap * x)
                start_y = canvas_padding + (cell_height * y) + (cell_gap * y)
                end_x = start_x + cell_width
                end_y = start_y + cell_height

                font_x = start_x + (cell_width / 2)
                font_y = start_y + (cell_height / 2)

                if y < len(guesses):
                    if guesses[y][x] in answer and guesses[y][x] != letter:
                        answer = ''.join(answer.split(guesses[y][x], 1))
                        frame.rectangle([(start_x, start_y), (end_x, end_y)], cell_yellow)
                    frame.text(xy = (font_x, font_y), text = guesses[y][x].upper(), fill = text_color, font = bold, anchor = "mm")

        return canvas

    async def keyboard(self, target_word, guesses):
        canvas_width = 500
        canvas_height = 200
        canvas_padding = 8

        key_gap = 6
        key_width = 43
        key_height = 58

        key_bg = (0, 0, 0, 0)
        key_default = (129, 131, 132, 255)
        key_grey = (58, 58, 60, 255)
        key_yellow = (181, 159, 59, 255)
        key_green = (83, 141, 78, 255)

        text_color = (208, 204, 198, 255)

        letters = "qwertyuiopasdfghjklzxcvbnm"

        HelveticaNeueBold = f"{bundled_data_path(self)}/HelveticaNeueBold.ttf"
        bold = ImageFont.truetype(HelveticaNeueBold, 14)

        canvas = Image.new("RGBA", (canvas_width, canvas_height), key_bg)
        frame = ImageDraw.Draw(canvas)
        
        for key_index, letter in enumerate(letters):
            if key_index < 10:
                start_x = canvas_padding + (key_width * key_index) + (key_gap * key_index)
                start_y = 0
            elif key_index >= 10 and key_index < 19:
                start_x = canvas_padding + (key_width / 2) + (key_width * (key_index - 10)) + (key_gap * (key_index - 10))
                start_y = key_height + key_gap
            else:
                start_x = canvas_padding + (key_width / 2) + (key_gap / 2) + (key_width * (key_index - 18)) + (key_gap * (key_index - 18))
                start_y = (key_height * 2) + (key_gap * 2)

            end_x = start_x + key_width
            end_y = start_y + key_height

            font_x = start_x + (key_width / 2)
            font_y = start_y + (key_height / 2)

            frame.rounded_rectangle([(start_x, start_y), (end_x, end_y)], radius = 4, fill = key_default)

            for guess in guesses:
                for i, guess_letter in enumerate(guess):
                    if letter == guess_letter and guess[i] not in target_word:
                        frame.rounded_rectangle([(start_x, start_y), (end_x, end_y)], radius = 4, fill = key_grey)

            for guess in guesses:
                for i, guess_letter in enumerate(guess):
                    if letter == guess_letter and guess[i] in target_word:
                        frame.rounded_rectangle([(start_x, start_y), (end_x, end_y)], radius = 4, fill = key_yellow)

            for guess in guesses:
                for i, guess_letter in enumerate(guess):
                    if letter == guess_letter and guess[i] == target_word[i]:
                        frame.rounded_rectangle([(start_x, start_y), (end_x, end_y)], radius = 4, fill = key_green)

            frame.text(xy = (font_x, font_y), text = letter.upper(), fill = text_color, font = bold, anchor = "mm")
                        
        return canvas

    # This place is not a place of honor.
    # No highly esteemed deed is commemorated here.
    # Nothing valued is here.
    async def profile(self, ctx, member: discord.Member, target_word = None, guesses = [], earned = 0, multiplier = 0):
        canvas_width = 500
        canvas_height = 444
        canvas_padding = 16

        statistics_width = 349
        statistics_height = 66
        statistics_padding = 10

        statistic_label_width = 87
        statistic_label_height = 14
        statistic_value_height = 42

        graph_width = 373
        graph_height = 154
        graph_padding = 4

        graph_label_width = 8
        graph_label_height = 20
        graph_bar_width = 365
        graph_bar_min = 25

        economy_width = 466
        economy_height = 81
        economy_padding = 10

        economy_label_width = 221

        heading_height = 38

        blank_bg = (0, 0, 0, 0)
        frame_bg = (44, 48, 50, 255)
        frame_border = (26, 26, 27, 255)

        green_bar = (83, 141, 78, 255)
        grey_bar = (58, 58, 60, 255)

        text_color = (215, 218, 220, 255)

        HelveticaNeueBold = f"{bundled_data_path(self)}/HelveticaNeueBold.ttf"
        HelveticaNeue = f"{bundled_data_path(self)}/HelveticaNeue.ttf"

        header = ImageFont.truetype(HelveticaNeueBold, 17)
        statistic_value = ImageFont.truetype(HelveticaNeue, 36)
        statistic_value_bold = ImageFont.truetype(HelveticaNeueBold, 36)
        statistic_label = ImageFont.truetype(HelveticaNeue, 12)
        graph_label = ImageFont.truetype(HelveticaNeue, 14)
        graph_bar_label = ImageFont.truetype(HelveticaNeueBold, 14)

        played = await self.config.member(member).played()
        total_wins = await self.config.member(member).total_wins()
        streak = await self.config.member(member).streak()
        max_streak = await self.config.member(member).max_streak()
        total_earnings = await self.config.member(member).total_earnings()

        canvas = Image.new("RGBA", (canvas_width, canvas_height), blank_bg)
        frame = ImageDraw.Draw(canvas)

        frame.rounded_rectangle([(0, 0), (canvas_width, canvas_height)], radius = 14, fill = frame_bg, width = 1, outline = frame_border)

        frame.text(xy = ((canvas_width / 2), (2 * canvas_padding + heading_height / 2)), text = f"{member.name.upper()}'S STATS", fill = text_color, font = header, anchor = "mm")

        frame.text(xy = ((canvas_width / 2 - 3 * statistic_label_width / 2), (2 * canvas_padding + heading_height + statistic_value_height / 2)), text = f"{await self.humanize_number(played)}", fill = text_color, font = statistic_value, anchor = "mm")
        frame.text(xy = ((canvas_width / 2 - statistic_label_width / 2), (2 * canvas_padding + heading_height + statistic_value_height / 2)), text = f"{100 * (total_wins / played if played else 0):.0f}", fill = text_color, font = statistic_value, anchor = "mm")
        frame.text(xy = ((canvas_width / 2 + statistic_label_width / 2), (2 * canvas_padding + heading_height + statistic_value_height / 2)), text = f"{await self.humanize_number(streak)}", fill = text_color, font = statistic_value, anchor = "mm")
        frame.text(xy = ((canvas_width / 2 + 3 * statistic_label_width / 2), (2 * canvas_padding + heading_height + statistic_value_height / 2)), text = f"{await self.humanize_number(max_streak)}", fill = text_color, font = statistic_value, anchor = "mm")

        frame.text(xy = ((canvas_width / 2 - 3 * statistic_label_width / 2), (2 * canvas_padding + heading_height + statistic_value_height + statistic_label_height / 2)), text = "Played", fill = text_color, font = statistic_label, anchor = "mm")
        frame.text(xy = ((canvas_width / 2 - statistic_label_width / 2), (2 * canvas_padding + heading_height + statistic_value_height + statistic_label_height / 2)), text = "Win %", fill = text_color, font = statistic_label, anchor = "mm")
        frame.text(xy = ((canvas_width / 2 + statistic_label_width / 2), (2 * canvas_padding + heading_height + statistic_value_height + statistic_label_height / 2)), text = "Current Streak", fill = text_color, font = statistic_label, anchor = "mm")
        frame.text(xy = ((canvas_width / 2 + 3 * statistic_label_width / 2), (2 * canvas_padding + heading_height + statistic_value_height + statistic_label_height / 2)), text = "Max Streak", fill = text_color, font = statistic_label, anchor = "mm")

        frame.text(xy = ((canvas_width / 2), (2 * canvas_padding + heading_height + statistics_height + heading_height / 2)), text = "GUESS DISTRIBUTION", fill = text_color, font = header, anchor = "mm")

        async with self.config.member(member).guess_distribution() as guess_distribution:
            guess_amounts = list(guess_distribution.values())
            max_guess_amount = max(guess_amounts)

        for i, guess_amount in enumerate(guess_amounts):
            percent_of_max = guess_amount / max_guess_amount if max_guess_amount else 0

            graph_label_x = canvas_width / 2 - graph_width / 2
            graph_label_y = 2 * canvas_padding + 2 * heading_height + statistics_height + statistics_padding / 2 + i * graph_padding + i * graph_label_height
            graph_bar_start_x = graph_label_x + graph_padding + graph_label_width
            graph_bar_start_y = graph_label_y
            graph_bar_end_x = max(graph_bar_start_x + graph_bar_min, graph_bar_start_x + percent_of_max * graph_bar_width)
            graph_bar_end_y = graph_bar_start_y + graph_label_height - 2
            graph_bar_label_x = graph_bar_end_x - graph_padding * 3

            frame.text(xy = (graph_label_x, graph_label_y), text = str(i + 1), fill = text_color, font = graph_label)

            if percent_of_max == 1:
                frame.rectangle([(graph_bar_start_x, graph_bar_start_y), (graph_bar_end_x, graph_bar_end_y)], green_bar)
            else:
                frame.rectangle([(graph_bar_start_x, graph_bar_start_y), (graph_bar_end_x, graph_bar_end_y)], grey_bar)

            frame.text(xy = (graph_bar_label_x, graph_label_y), text = str(guess_amount), fill = text_color, font = graph_bar_label, anchor = "ma")

        frame.line(xy = ([(canvas_padding + economy_width / 2, 2 * canvas_padding + 2 * heading_height + statistics_height + graph_height), (canvas_padding + economy_width / 2, 2 * canvas_padding + 2 * heading_height + statistics_height + graph_height + economy_height)]), fill = text_color, width = 1)

        if earned:
            frame.text(xy = (canvas_padding + economy_label_width / 2, 2 * canvas_padding + 2 * heading_height + statistics_height + graph_height + heading_height / 2), text = f"EARNED {str(await bank.get_currency_name(ctx.guild)).upper()} (x{multiplier:.2f})", fill = text_color, font = header, anchor = "mm")

            frame.text(xy = (canvas_padding + economy_label_width / 2, 2 * canvas_padding + 3 * heading_height + statistics_height + graph_height + statistic_value_height / 2), text = f"{await self.humanize_number(earned)}", fill = text_color, font = statistic_value_bold, anchor = "mm")
        else:
            frame.text(xy = (canvas_padding + economy_label_width / 2, 2 * canvas_padding + 2 * heading_height + statistics_height + graph_height + heading_height / 2), text = f"LIFETIME EARNINGS", fill = text_color, font = header, anchor = "mm")

            frame.text(xy = (canvas_padding + economy_label_width / 2, 2 * canvas_padding + 3 * heading_height + statistics_height + graph_height + statistic_value_height / 2), text = f"{await self.humanize_number(total_earnings)}", fill = text_color, font = statistic_value_bold, anchor = "mm")

        if target_word:
            frame.text(xy = (canvas_width - canvas_padding - economy_label_width / 2, 2 * canvas_padding + 2 * heading_height + statistics_height + graph_height + heading_height / 2), text = f"THE WORD WAS", fill = text_color, font = header, anchor = "mm")

            if target_word in guesses:
                frame.text(xy = (canvas_width - canvas_padding - economy_label_width / 2, 2 * canvas_padding + 3 * heading_height + statistics_height + graph_height + statistic_value_height / 2), text = f"{target_word.upper()}", fill = green_bar, font = statistic_value_bold, anchor = "mm")
            else:
                frame.text(xy = (canvas_width - canvas_padding - economy_label_width / 2, 2 * canvas_padding + 3 * heading_height + statistics_height + graph_height + statistic_value_height / 2), text = f"{target_word.upper()}", fill = text_color, font = statistic_value_bold, anchor = "mm")
        else:
            frame.text(xy = (canvas_width - canvas_padding - economy_label_width / 2, 2 * canvas_padding + 2 * heading_height + statistics_height + graph_height + heading_height / 2), text = f"SERVER RANK", fill = text_color, font = header, anchor = "mm")

            rank = await self.get_rank(ctx, member)
            members = len(ctx.guild.members)

            frame.text(xy = (canvas_width - canvas_padding - economy_label_width / 2, 2 * canvas_padding + 3 * heading_height + statistics_height + graph_height + statistic_value_height / 2), text = f"#{rank}/{members}" if rank else text = f"No Data", fill = text_color, font = statistic_value_bold, anchor = "mm")

        return canvas

    async def combine(self, canvas, combine):
        combine.thumbnail(canvas.size)

        bg = (0, 0, 0, 0)

        img = Image.new("RGBA", (min(canvas.width, combine.width), canvas.height + combine.height), bg)
        img.paste(canvas, (0, 0))
        img.paste(combine, (0, canvas.height))

        return await self.save_image(img)

    async def save_image(self, img):
        file = BytesIO()
        img.save(file, "PNG", quality = 100)
        file.seek(0)
        return file

    async def humanize_number(self, number):
        if not number:
            return 0

        number = float(f"{number:.3g}")
        magnitude = 0

        while abs(number) >= 1000:
            magnitude += 1
            number /= 1000.0

        return f"{number:.0f}{['', 'k', 'm', 'b', 't'][magnitude])}"

    async def get_rank(self, ctx, member):
        members = await self.config.all_members(ctx.guild)
        members = {ctx.guild.get_member(u): d for u, d in members.items()}
        members.pop(None, None)

        items = members.items()

        leaderboard = sorted(members.items(), key=lambda x: x[1]["total_wins"], reverse=True)

        for i, user in enumerate(leaderboard):
            if user[0].id == member.id:
                return i + 1
