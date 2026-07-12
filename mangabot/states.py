from aiogram.fsm.state import State, StatesGroup


class MangaSearchState(StatesGroup):
    waiting_query = State()


class ReadProgressState(StatesGroup):
    waiting_chapter = State()

