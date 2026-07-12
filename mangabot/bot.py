from __future__ import annotations

import asyncio
import html
import logging
from contextlib import suppress
from typing import Optional

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, CallbackQuery, Message

from .config import Settings, load_settings
from .database import Database
from .keyboards import (
    main_menu_keyboard,
    manga_actions_keyboard,
    manga_list_keyboard,
    search_results_keyboard,
)
from .models import MangaChapter
from .remanga import ReMangaClient
from .states import MangaSearchState, ReadProgressState


logger = logging.getLogger(__name__)


def _is_newer(previous_index: Optional[int], previous_id: Optional[int], chapter: MangaChapter) -> bool:
    if previous_index is None:
        return True
    if chapter.index > previous_index:
        return True
    if chapter.index == previous_index and previous_id is not None and chapter.id > previous_id:
        return True
    return False


def _format_subscription(row) -> str:
    last_read = row["last_read_chapter_label"] or "не отмечено"
    latest = row["latest_chapter_label"] or "нет данных"
    unread = max(0, int(row["latest_chapter_index"] or 0) - int(row["last_read_chapter_index"] or 0))

    return (
        f"<b>{html.escape(row['title'])}</b>\n"
        f"Тип: {html.escape(row['type_name'] or 'не указан')}\n"
        f"Статус: {html.escape(row['status_name'] or 'не указан')}\n"
        f"Прочитано до: <b>{html.escape(str(last_read))}</b>\n"
        f"Последняя известная глава: <b>{html.escape(str(latest))}</b>\n"
        f"Непрочитанных глав: <b>{unread}</b>\n"
        f"<a href=\"{html.escape(row['site_url'])}\">Открыть на ReManga</a>"
    )


class MangaBotApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.db_path)
        self.db.init_schema()
        self.router = Router()
        self.dp = Dispatcher(storage=MemoryStorage())
        self.dp.include_router(self.router)

        self.session: Optional[aiohttp.ClientSession] = None
        self.client: Optional[ReMangaClient] = None
        self._notifier_task: Optional[asyncio.Task] = None

        self._register_handlers()
        self.dp.startup.register(self.on_startup)
        self.dp.shutdown.register(self.on_shutdown)

    def _register_handlers(self) -> None:
        self.router.message.register(self.cmd_start, CommandStart())
        self.router.message.register(self.cmd_help, Command("help"))
        self.router.message.register(self.cmd_search, Command("search"))
        self.router.message.register(self.cmd_list, Command("list"))
        self.router.message.register(self.cmd_check, Command("check"))
        self.router.message.register(self.cmd_cancel, Command("cancel"))

        self.router.message.register(self.open_search_prompt, F.text == "Добавить мангу")
        self.router.message.register(self.show_user_list, F.text == "Мои манги")
        self.router.message.register(self.cmd_check, F.text == "Проверить обновления")
        self.router.message.register(self.cmd_help, F.text == "Помощь")

        self.router.message.register(
            self.handle_search_query,
            MangaSearchState.waiting_query,
        )
        self.router.message.register(
            self.handle_read_chapter_input,
            ReadProgressState.waiting_chapter,
        )

        self.router.callback_query.register(self.handle_add_manga, F.data.startswith("add:"))
        self.router.callback_query.register(self.handle_open_manga, F.data.startswith("open:"))
        self.router.callback_query.register(
            self.handle_mark_latest_as_read,
            F.data.startswith("read_latest:"),
        )
        self.router.callback_query.register(
            self.handle_prompt_set_read,
            F.data.startswith("set_read:"),
        )
        self.router.callback_query.register(self.handle_delete_manga, F.data.startswith("delete:"))

    async def on_startup(self, bot: Bot) -> None:
        self.session = aiohttp.ClientSession(
            headers={
                "Origin": "https://remanga.org",
                "Referer": "https://remanga.org/",
                "Accept-Language": "ru,en;q=0.8",
            }
        )
        self.client = ReMangaClient(self.session)

        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Главное меню"),
                BotCommand(command="help", description="Показать помощь"),
                BotCommand(command="search", description="Найти и добавить мангу"),
                BotCommand(command="list", description="Показать мой список"),
                BotCommand(command="check", description="Проверить новые главы"),
                BotCommand(command="cancel", description="Отменить ввод"),
            ]
        )

        self._notifier_task = asyncio.create_task(self.notification_loop(bot))
        logger.info("Бот запущен.")

    async def on_shutdown(self, bot: Bot) -> None:
        if self._notifier_task:
            self._notifier_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._notifier_task

        if self.session:
            await self.session.close()

        self.db.close()
        logger.info("Бот остановлен.")

    async def notification_loop(self, bot: Bot) -> None:
        while True:
            try:
                sent = await self.check_for_updates(bot)
                if sent:
                    logger.info("Отправлено уведомлений о новых главах: %s", sent)
            except Exception:
                logger.exception("Ошибка в цикле проверки новых глав.")
            await asyncio.sleep(self.settings.check_interval_seconds)

    async def cmd_start(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer(
            (
                "MangaBotForSlavyan готов к работе.\n\n"
                "Основные действия:\n"
                "- добавить мангу с ReManga;\n"
                "- отслеживать новые главы;\n"
                "- хранить прочитанную главу отдельно по каждой манге."
            ),
            reply_markup=main_menu_keyboard(),
        )

    async def cmd_help(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer(
            (
                "Команды:\n"
                "/search - найти и добавить мангу\n"
                "/list - показать мой список\n"
                "/check - вручную проверить новые главы\n"
                "/cancel - отменить текущий ввод\n\n"
                "После добавления манги откройте её карточку и отметьте, "
                "до какой главы вы дочитали."
            ),
            reply_markup=main_menu_keyboard(),
        )

    async def cmd_search(self, message: Message, state: FSMContext) -> None:
        await self.open_search_prompt(message, state)

    async def open_search_prompt(self, message: Message, state: FSMContext) -> None:
        await state.set_state(MangaSearchState.waiting_query)
        await message.answer(
            "Напишите название манги, которое нужно найти на ReManga.",
            reply_markup=main_menu_keyboard(),
        )

    async def handle_search_query(self, message: Message, state: FSMContext) -> None:
        if not message.text:
            await message.answer("Отправьте текстовое название манги.")
            return

        query = message.text.strip()
        if len(query) < 2:
            await message.answer("Введите хотя бы 2 символа для поиска.")
            return

        assert self.client is not None

        try:
            results = await self.client.search_titles(query, limit=self.settings.search_limit)
        except Exception:
            logger.exception("Ошибка поиска манги.")
            await message.answer("Не удалось выполнить поиск на ReManga. Попробуйте позже.")
            return

        if not results:
            await message.answer("По этому запросу ничего не нашлось. Попробуйте другое название.")
            return

        await state.clear()
        keyboard_items = [
            {"dir_name": item.dir_name, "title": item.title}
            for item in results
        ]
        lines = []
        for index, item in enumerate(results, start=1):
            issue_year = f" ({item.issue_year})" if item.issue_year else ""
            lines.append(f"{index}. {item.title}{issue_year}")

        await message.answer(
            "Результаты поиска:\n" + "\n".join(lines),
            reply_markup=search_results_keyboard(keyboard_items),
        )

    async def cmd_list(self, message: Message, state: FSMContext) -> None:
        await self.show_user_list(message, state)

    async def show_user_list(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        items = self.db.get_user_subscriptions(message.from_user.id)
        if not items:
            await message.answer(
                "Список пока пуст. Используйте /search или кнопку \"Добавить мангу\".",
                reply_markup=main_menu_keyboard(),
            )
            return

        await message.answer(
            "Ваш список манги:",
            reply_markup=manga_list_keyboard(items),
        )

    async def handle_add_manga(self, callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        dir_name = callback.data.split(":", 1)[1]

        assert self.client is not None

        try:
            manga = await self.client.get_title(dir_name)
            latest_chapter = await self.client.get_latest_chapter(manga.branch.id)
        except Exception:
            logger.exception("Ошибка при добавлении манги.")
            await callback.message.answer("Не удалось получить данные тайтла с ReManga.")
            return

        self.db.upsert_manga(manga, latest_chapter)
        self.db.add_subscription(callback.from_user.id, manga.id)

        latest_label = latest_chapter.display_name if latest_chapter else "главы пока не найдены"
        await callback.message.answer(
            (
                f"Манга <b>{html.escape(manga.title)}</b> добавлена.\n"
                f"Последняя известная глава: <b>{html.escape(latest_label)}</b>\n\n"
                "Теперь можно отметить последнюю прочитанную главу."
            ),
            reply_markup=manga_actions_keyboard(manga.id),
        )
        await state.clear()

    async def handle_open_manga(self, callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        manga_id = int(callback.data.split(":", 1)[1])
        row = self.db.get_subscription(callback.from_user.id, manga_id)
        if not row:
            await callback.message.answer("Эта манга не найдена в вашем списке.")
            return

        await state.clear()
        await callback.message.answer(
            _format_subscription(row),
            reply_markup=manga_actions_keyboard(manga_id),
        )

    async def handle_mark_latest_as_read(self, callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        manga_id = int(callback.data.split(":", 1)[1])
        row = self.db.get_subscription(callback.from_user.id, manga_id)
        if not row:
            await callback.message.answer("Эта манга не найдена в вашем списке.")
            return

        assert self.client is not None

        try:
            latest_chapter = await self.client.get_latest_chapter(int(row["branch_id"]))
        except Exception:
            logger.exception("Ошибка при получении последней главы.")
            await callback.message.answer("Не удалось получить последнюю главу с ReManga.")
            return

        if latest_chapter is None:
            await callback.message.answer("У этой манги пока нет доступных глав.")
            return

        self.db.update_latest_chapter(manga_id, latest_chapter)
        self.db.update_read_progress(callback.from_user.id, manga_id, latest_chapter)

        await state.clear()
        await callback.message.answer(
            (
                f"Для <b>{html.escape(row['title'])}</b> отмечено прочтение до "
                f"<b>{html.escape(latest_chapter.chapter_label)}</b>."
            ),
            reply_markup=manga_actions_keyboard(manga_id),
        )

    async def handle_prompt_set_read(self, callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        manga_id = int(callback.data.split(":", 1)[1])
        row = self.db.get_subscription(callback.from_user.id, manga_id)
        if not row:
            await callback.message.answer("Эта манга не найдена в вашем списке.")
            return

        await state.set_state(ReadProgressState.waiting_chapter)
        await state.update_data(manga_id=manga_id)
        await callback.message.answer(
            (
                f"Введите номер главы для <b>{html.escape(row['title'])}</b>.\n"
                "Можно указать номер главы с ReManga, например: 12, 45 или 12.5"
            )
        )

    async def handle_read_chapter_input(self, message: Message, state: FSMContext) -> None:
        if not message.text:
            await message.answer("Отправьте номер главы текстом.")
            return

        data = await state.get_data()
        manga_id = data.get("manga_id")
        if manga_id is None:
            await state.clear()
            await message.answer("Контекст выбора потерян. Откройте мангу ещё раз.")
            return

        row = self.db.get_subscription(message.from_user.id, int(manga_id))
        if not row:
            await state.clear()
            await message.answer("Манга не найдена в вашем списке.")
            return

        assert self.client is not None

        try:
            chapter = await self.client.find_chapter(int(row["branch_id"]), message.text)
        except Exception:
            logger.exception("Ошибка поиска главы.")
            await message.answer("Не удалось проверить список глав на ReManga.")
            return

        if chapter is None:
            await message.answer("Такую главу не удалось найти. Попробуйте другой номер.")
            return

        self.db.update_read_progress(message.from_user.id, int(manga_id), chapter)
        await state.clear()
        await message.answer(
            (
                f"Для <b>{html.escape(row['title'])}</b> отмечено прочтение до "
                f"<b>{html.escape(chapter.chapter_label)}</b>."
            ),
            reply_markup=manga_actions_keyboard(int(manga_id)),
        )

    async def handle_delete_manga(self, callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        manga_id = int(callback.data.split(":", 1)[1])
        row = self.db.get_subscription(callback.from_user.id, manga_id)
        if not row:
            await callback.message.answer("Эта манга уже удалена из вашего списка.")
            return

        self.db.delete_subscription(callback.from_user.id, manga_id)
        await state.clear()
        await callback.message.answer(
            f"Манга <b>{html.escape(row['title'])}</b> удалена из вашего списка.",
            reply_markup=main_menu_keyboard(),
        )

    async def cmd_check(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        sent = await self.check_for_updates(message.bot, only_user_id=message.from_user.id)
        if sent == 0:
            await message.answer("Новых глав для вашей манги пока не найдено.")
            return

        await message.answer(
            f"Проверка завершена. Найдено обновлений: {sent}.",
            reply_markup=main_menu_keyboard(),
        )

    async def cmd_cancel(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Текущий ввод отменён.", reply_markup=main_menu_keyboard())

    async def check_for_updates(self, bot: Optional[Bot], only_user_id: Optional[int] = None) -> int:
        assert self.client is not None
        sent_messages = 0

        tracked_manga = self.db.list_tracked_manga()
        for row in tracked_manga:
            try:
                latest_chapters = await self.client.get_latest_chapters(int(row["branch_id"]), limit=10)
            except Exception:
                logger.exception("Ошибка проверки манги %s", row["title"])
                continue

            if not latest_chapters:
                continue

            previous_index = row["latest_chapter_index"]
            previous_id = row["latest_chapter_id"]
            new_chapters = [
                chapter
                for chapter in reversed(latest_chapters)
                if _is_newer(previous_index, previous_id, chapter)
            ]

            latest_chapter = latest_chapters[0]
            self.db.update_latest_chapter(int(row["id"]), latest_chapter)

            if not new_chapters:
                continue

            subscribers = self.db.list_subscribers_for_manga(int(row["id"]))
            for subscriber in subscribers:
                if only_user_id is not None and int(subscriber["user_id"]) != only_user_id:
                    continue

                unread_from_user = [
                    chapter
                    for chapter in new_chapters
                    if chapter.index > int(subscriber["last_read_chapter_index"] or 0)
                ]
                chapters_preview = "\n".join(
                    f"- {html.escape(chapter.display_name)}" for chapter in new_chapters[:5]
                )
                unread_count = max(
                    0,
                    int(latest_chapter.index) - int(subscriber["last_read_chapter_index"] or 0),
                )
                unread_note = (
                    f"\nНовых лично для вас: <b>{len(unread_from_user)}</b>. "
                    f"Всего непрочитанных сейчас: <b>{unread_count}</b>."
                )

                text = (
                    f"Для <b>{html.escape(row['title'])}</b> появились новые главы:\n"
                    f"{chapters_preview}{unread_note}\n"
                    f"<a href=\"{html.escape(row['site_url'])}\">Открыть тайтл на ReManga</a>"
                )

                if bot is not None:
                    await bot.send_message(int(subscriber["user_id"]), text)
                sent_messages += 1

        return sent_messages

    async def start_polling(self) -> None:
        bot = Bot(
            token=self.settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        await self.dp.start_polling(bot)


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_settings()
    app = MangaBotApp(settings)
    asyncio.run(app.start_polling())
