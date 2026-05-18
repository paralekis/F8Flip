import keyboard
import mouse
import time
import ctypes
from ctypes import wintypes
import os
import json
import tkinter as tk
from tkinter import messagebox
import threading
import winreg
import sys

# --- КОНСТАНТИ ---
CONFIG_FILE = "config.json"
APP_NAME = "F8Flip"

ENG_SET = set("qwertyuiopasdfghjklzxcvbnmQWERTYUIOPASDFGHJKLZXCVBNM[]{}'\"`~<>;:")
CYR_SET = set("йцукенгшщзхїфівапролджєячсмитьбюЙЦУКЕНГШЩЗХЇФІВАПРОЛДЖЄЯЧСМИТЬБЮъыэёЪЫЭЁ")

ENG_CHARS = "qwertyuiop[]asdfghjkl;'zxcvbnm,./`QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>?~"
UKR_CHARS = "йцукенгшщзхїфівапролджєячсмитьбю.ʼЙЦУКЕНГШЩЗХЇФІВАПРОЛДЖЄЯЧСМИТЬБЮ,₴"
RU_CHARS = "йцукенгшщзхъфывапролджэячсмитьбю.ёЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,Ё"

eng_to_ukr = str.maketrans(ENG_CHARS, UKR_CHARS)
eng_to_ru = str.maketrans(ENG_CHARS, RU_CHARS)
cyrillic_to_eng = str.maketrans(UKR_CHARS + RU_CHARS, ENG_CHARS + ENG_CHARS)

MAX_BUFFER_LENGTH = 500

# Розширений список клавіш, які скидають буфер
RESET_KEYS = {
    'enter', 'tab', 'esc', 'up', 'down', 'left', 'right',
    'page up', 'page down', 'home', 'end',
    'alt', 'left alt', 'right alt', 'windows', 'left windows'
}
MODIFIERS = {'ctrl', 'left ctrl', 'right ctrl', 'alt', 'left alt', 'right alt', 'shift', 'left shift', 'right shift'}

WM_INPUTLANGCHANGEREQUEST = 0x0050
LANG_EN = 0x0409
LANG_UKR = 0x0422
LANG_RU = 0x0419

user32 = ctypes.windll.user32
user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.PostMessageW.restype = wintypes.BOOL


# --- ЛОГІКА АВТОЗАВАНТАЖЕННЯ ---
def get_startup_path():
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}"'
    return f'"{os.path.abspath(sys.argv[0])}"'


def is_in_startup():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                             winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return value == get_startup_path()
    except OSError:
        return False


def set_startup(enable):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                             winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, get_startup_path())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except OSError:
        pass


# --- WINDOWS API ХЕЛПЕРИ ---
def release_all_modifiers():
    vks = [0x10, 0xA0, 0xA1, 0x11, 0xA2, 0xA3, 0x12, 0xA4, 0xA5]
    for vk in vks:
        user32.keybd_event(vk, 0, 0x0002, 0)


def get_current_layout():
    hwnd = user32.GetForegroundWindow()
    thread_id = user32.GetWindowThreadProcessId(hwnd, 0)
    layout = user32.GetKeyboardLayout(thread_id)
    return layout & 0xFFFF


def get_hkl_for_language(lang_id):
    count = user32.GetKeyboardLayoutList(0, None)
    hkl_array = (ctypes.c_void_p * count)()
    user32.GetKeyboardLayoutList(count, hkl_array)
    for hkl in hkl_array:
        if hkl is not None and (hkl & 0xFFFF) == lang_id:
            return hkl
    return None


def set_system_layout(hkl_code):
    if hkl_code:
        hwnd = user32.GetForegroundWindow()
        user32.PostMessageW(hwnd, WM_INPUTLANGCHANGEREQUEST, 0, hkl_code)


# --- ОСНОВНИЙ КЛАС ДОДАТКУ ---
class Flip8App:
    def __init__(self):
        self.current_buffer = ""
        self.is_switching = False
        self.cycle_sequence = []
        self.cycle_index = 0
        self.current_hotkey = "f8"

        self.modifier_down_time = 0
        self.combo_pressed = False
        self.just_switched = False
        self.last_f8_time = 0

        # Відслідковування активного вікна
        self.last_hwnd = user32.GetForegroundWindow()

        self.load_or_create_config()

        mouse.on_click(self.reset_buffer)
        keyboard.hook(self.process_key)

        self.register_hotkey()
        keyboard.add_hotkey('ctrl+win+f8', self.change_hotkey_runtime)

    def reset_buffer(self):
        self.current_buffer = ""
        self.cycle_sequence = []
        self.just_switched = False
        self.last_hwnd = user32.GetForegroundWindow()

    def check_window_changed(self):
        current_hwnd = user32.GetForegroundWindow()
        if current_hwnd != self.last_hwnd:
            self.reset_buffer()
            self.last_hwnd = current_hwnd

    def process_key(self, event):
        if self.is_switching:
            return

        # 1. Перевірка зміни вікна (щоб уникнути заміни тексту в іншій програмі)
        if event.event_type == keyboard.KEY_DOWN:
            self.check_window_changed()

        # 2. Відслідковування гарячої клавіші (якщо це модифікатор)
        if self.current_hotkey in MODIFIERS:
            if event.name.lower() == self.current_hotkey:
                if event.event_type == keyboard.KEY_DOWN:
                    if self.modifier_down_time == 0:
                        self.modifier_down_time = time.time()
                        self.combo_pressed = False
                elif event.event_type == keyboard.KEY_UP:
                    if self.modifier_down_time != 0 and not self.combo_pressed:
                        if time.time() - self.modifier_down_time < 0.5:
                            threading.Thread(target=self.switch_layout, daemon=True).start()
                    self.modifier_down_time = 0
                return
            else:
                if event.event_type == keyboard.KEY_DOWN:
                    self.combo_pressed = True

        # 3. Скидання буфера при спробі вставити текст з буфера обміну (Ctrl+V)
        if event.event_type == keyboard.KEY_DOWN and event.name.lower() == 'v' and keyboard.is_pressed('ctrl'):
            self.reset_buffer()
            return

        if event.event_type != keyboard.KEY_DOWN:
            return

        name = event.name

        if len(name) == 1 or name == 'space' or name == 'backspace':
            self.cycle_sequence = []
            if self.just_switched:
                self.current_buffer = ""
                self.just_switched = False

        if len(name) == 1:
            self.current_buffer += name
            if len(self.current_buffer) > MAX_BUFFER_LENGTH:
                self.current_buffer = self.current_buffer[-MAX_BUFFER_LENGTH:]
        elif name == 'space':
            self.current_buffer += ' '
            if len(self.current_buffer) > MAX_BUFFER_LENGTH:
                self.current_buffer = self.current_buffer[-MAX_BUFFER_LENGTH:]
        elif name == 'backspace':
            self.current_buffer = self.current_buffer[:-1]
        elif name in RESET_KEYS:
            self.reset_buffer()

    def switch_layout(self):
        if not self.current_buffer:
            return

        self.is_switching = True
        try:
            release_all_modifiers()

            now = time.time()
            is_in_cycle = (now - self.last_f8_time < 1.5) and len(self.cycle_sequence) > 0

            if not is_in_cycle:
                eng_c = sum(1 for c in self.current_buffer if c in ENG_SET)
                cyr_c = sum(1 for c in self.current_buffer if c in CYR_SET)

                if eng_c >= cyr_c:
                    base_keys = self.current_buffer
                else:
                    base_keys = self.current_buffer.translate(cyrillic_to_eng)

                v_eng = (base_keys, LANG_EN)
                v_ukr = (base_keys.translate(eng_to_ukr), LANG_UKR)
                v_ru = (base_keys.translate(eng_to_ru), LANG_RU)

                layout_id = get_current_layout()
                if layout_id == 1058:
                    raw_sequence = [v_eng, v_ru, v_ukr]
                elif layout_id == 1049:
                    raw_sequence = [v_eng, v_ukr, v_ru]
                else:
                    raw_sequence = [v_ukr, v_ru, v_eng]

                self.cycle_sequence = []
                seen_texts = set()
                for item_text, lang_id in raw_sequence:
                    if get_hkl_for_language(lang_id) is not None:
                        if item_text not in seen_texts:
                            seen_texts.add(item_text)
                            self.cycle_sequence.append((item_text, lang_id))
                if not self.cycle_sequence:
                    self.cycle_sequence.append((base_keys, LANG_EN))
                self.cycle_index = 0
            else:
                self.cycle_index = (self.cycle_index + 1) % len(self.cycle_sequence)

            fixed_text, target_lang_id = self.cycle_sequence[self.cycle_index]
            buffer_length = len(self.current_buffer)

            # ОПТИМІЗОВАНЕ ВИДАЛЕННЯ З БЕЗПЕЧНИМИ ЗАТРИМКАМИ
            if buffer_length > 10:
                for _ in range(buffer_length):
                    keyboard.send('shift+left')
                    time.sleep(0.001)  # Захист від пропуску кадрів у важких програмах
                keyboard.send('backspace')
            else:
                for _ in range(buffer_length):
                    keyboard.send('backspace')
                    time.sleep(0.001)

            keyboard.write(fixed_text, delay=0.002, restore_state_after=False)

            target_hkl = get_hkl_for_language(target_lang_id)
            set_system_layout(target_hkl)

            self.current_buffer = fixed_text
            self.last_f8_time = now
            self.just_switched = True

        finally:
            self.is_switching = False

    # --- ГРАФІЧНИЙ ІНТЕРФЕЙС ТА НАЛАШТУВАННЯ ---
    def ask_user_for_hotkey(self, initial_value="f8"):
        result_key = initial_value
        result_startup = is_in_startup()
        saved = False

        root = tk.Tk()
        root.title("Flip8 - Налаштування")
        root.geometry("340x380")
        root.resizable(False, False)
        root.attributes("-topmost", True)
        root.eval('tk::PlaceWindow . center')

        chosen_key = tk.StringVar(value=initial_value)
        tk.Label(root, text="Оберіть гарячу клавішу\nдля перемикання розкладки:", font=("Segoe UI", 11, "bold"),
                 pady=15).pack()

        options = [
            ("Клавіша F8 (Рекомендовано)", "f8"),
            ("Клавіша Pause", "pause"),
            ("Клавіша Caps Lock", "caps lock"),
            ("Правий Ctrl", "right ctrl"),
            ("Правий Alt", "right alt")
        ]

        frame = tk.Frame(root)
        frame.pack(pady=5)

        for text, val in options:
            rb = tk.Radiobutton(frame, text=text, variable=chosen_key, value=val, font=("Segoe UI", 10), cursor="hand2")
            rb.pack(anchor="w", pady=2)

        startup_var = tk.BooleanVar(value=result_startup)
        tk.Checkbutton(root, text="Запускати автоматично з Windows", variable=startup_var,
                       font=("Segoe UI", 10, "italic"), cursor="hand2").pack(pady=10)

        def on_save():
            nonlocal result_key, result_startup, saved
            result_key = chosen_key.get()
            result_startup = startup_var.get()
            saved = True
            root.quit()

        tk.Button(root, text="Зберегти", command=on_save, font=("Segoe UI", 10, "bold"), bg="#0078D7", fg="white",
                  width=20, cursor="hand2").pack(pady=5)
        tk.Label(root, text="(Це меню завжди можна викликати\nкомбінацією Ctrl + Win + F8)", font=("Segoe UI", 8),
                 fg="gray").pack(side="bottom", pady=10)

        def on_closing():
            nonlocal result_key, result_startup, saved
            result_key = initial_value
            result_startup = is_in_startup()
            saved = False
            root.quit()

        root.protocol("WM_DELETE_WINDOW", on_closing)
        root.mainloop()
        root.destroy()
        return result_key, result_startup, saved

    def load_or_create_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    self.current_hotkey = config.get("hotkey", "f8")
            except (json.JSONDecodeError, OSError):
                self.current_hotkey = "f8"
        else:
            chosen_key, run_on_startup, saved = self.ask_user_for_hotkey("f8")
            if saved:
                self.current_hotkey = chosen_key
                set_startup(run_on_startup)
            else:
                self.current_hotkey = "f8"
            self.save_config(self.current_hotkey)

    def save_config(self, hotkey_value):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({"hotkey": hotkey_value}, f, ensure_ascii=False, indent=4)
        except OSError:
            # Якщо файл заблоковано, просто продовжуємо роботу
            pass

    def register_hotkey(self):
        try:
            keyboard.remove_hotkey(self.switch_layout)
        except (KeyError, ValueError):
            pass

        if self.current_hotkey not in MODIFIERS:
            keyboard.add_hotkey(self.current_hotkey, self.switch_layout, suppress=True)

    def change_hotkey_runtime(self):
        self.reset_buffer()
        new_key, run_on_startup, saved = self.ask_user_for_hotkey(self.current_hotkey)

        if saved:
            set_startup(run_on_startup)
            if new_key != self.current_hotkey:
                self.current_hotkey = new_key
                self.save_config(self.current_hotkey)
                self.modifier_down_time = 0
                self.combo_pressed = False
                self.register_hotkey()

            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo("Flip8", "Налаштування успішно збережено!")
            root.destroy()


if __name__ == "__main__":
    app = Flip8App()
    keyboard.wait()