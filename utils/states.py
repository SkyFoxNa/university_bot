from aiogram.fsm.state import StatesGroup, State
from aiogram.filters.callback_data import CallbackData


class UserManage(CallbackData, prefix="user_m"):
    action: str  # 'list', 'details', 'edit_role', 'edit_num'
    user_id: int = 0
    page: int = 0
    role_name: str = "" # Для перемикання ролей


class UserEditStates(StatesGroup):
    waiting_for_number = State()  # Очікування номера за журналом

class HomeworkStates(StatesGroup):
    waiting_for_description = State()   # Крок 1
    waiting_for_task_link = State()     # Крок 2
    waiting_for_video_link = State()    # Крок 3
    waiting_for_extra_link = State()    # Крок 4
    waiting_for_note = State()          # Крок 5
    confirm_add = State()               # Підтвердження
    waiting_for_new_value = State()     # Універсальний стан для редагування будь-якого поля


class SubjectStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_teacher = State()
    waiting_for_zoom_link = State()
    waiting_for_zoom_id = State()
    waiting_for_zoom_password = State()


# робота викладача з вибором предмета для викладання
class TeachingManage(CallbackData, prefix="teach"):
    action: str  # 'select', 'confirm', 'detach'
    subject_id: int = 0

# стан для телефона, email, viber, telegram
class ProfileEdit(StatesGroup):
    waiting_for_input = State()  # Універсальний стан для введення тексту


# стан для вибору пар на розклад занять
class ScheduleEdit(StatesGroup):
    waiting_for_subject = State()  # Вибір предмета зі списку
    waiting_for_type = State()     # Ввід типу (лекція/практика)
    waiting_for_color = State()    # Вибір кольору тижня
    subj_waiting_for_type = State()


# стан для зміни розкладу
class ScheduleChange(StatesGroup):
    waiting_for_subject = State()
    waiting_for_date = State()
    confirm = State()

