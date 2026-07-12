from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Добавить мангу"), KeyboardButton(text="Мои манги")],
            [KeyboardButton(text="Проверить обновления"), KeyboardButton(text="Помощь")],
        ],
        resize_keyboard=True,
    )


def search_results_keyboard(results: list[dict[str, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in results:
        builder.button(
            text=f"Добавить: {item['title'][:45]}",
            callback_data=f"add:{item['dir_name']}",
        )
    builder.adjust(1)
    return builder.as_markup()


def manga_list_keyboard(items: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.button(
            text=item["title"][:55],
            callback_data=f"open:{item['manga_id']}",
        )
    builder.adjust(1)
    return builder.as_markup()


def manga_actions_keyboard(manga_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Отметить последнюю прочитанной", callback_data=f"read_latest:{manga_id}")
    builder.button(text="Указать главу вручную", callback_data=f"set_read:{manga_id}")
    builder.button(text="Удалить из списка", callback_data=f"delete:{manga_id}")
    builder.adjust(1)
    return builder.as_markup()

