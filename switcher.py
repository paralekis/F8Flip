import time
import threading
import keyboard
import mouse
import ctypes
from ctypes import wintypes
import os
import json
import tkinter as tk
from tkinter import messagebox
import winreg
import sys
import queue

# --- КОНСТАНТИ ТА НАЛАШТУВАННЯ ---
CONFIG_FILE = "config.json"
APP_NAME = "F8Flip"

# СПИСОК ЖОРСТКИХ ВИНЯТКІВ
IGNORE_APPS = {
    "acs.exe"  # Assetto Corsa
}

# СПИСОК РОЗУМНИХ ПРОГРАМ (Захист для 3D/2D редакторів)
SMART_HEURISTIC_APPS = {
    "blender.exe",
    "3dsmax.exe",
    "photoshop.exe",
    "zbrush.exe",
    "maya.exe"
}

ENG_SET = set("qwertyuiopasdfghjklzxcvbnmQWERTYUIOPASDFGHJKLZXCVBNM[]{}'\"`~<>;:")
CYR_SET = set("йцукенгшщзхїфівапролджєячсмитьбюЙЦУКЕНГШЩЗХЇФІВАПРОЛДЖЄЯЧСМИТЬБЮъыэёЪЫЭЁ")

ENG_CHARS = "qwertyuiop[]asdfghjkl;'zxcvbnm,./`QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>?~"
UKR_CHARS = "йцукенгшщзхїфівапролджєячсмитьбю.ʼЙЦУКЕНГШЩЗХЇФІВАПРОЛДЖЄЯЧСМИТЬБЮ,₴"
RU_CHARS = "йцукенгшщзхъфывапролджэячсмитьбю.ёЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,Ё"

eng_to_ukr = str.maketrans(ENG_CHARS, UKR_CHARS)
eng_to_ru = str.maketrans(ENG_CHARS, RU_CHARS)
cyrillic_to_eng = str.maketrans(UKR_CHARS + RU_CHARS, ENG_CHARS + ENG_CHARS)

# Зменшено для уникнення занадто довгого видалення тексту через Backspace
MAX_BUFFER_LENGTH = 200

RESET_KEYS = {
    'enter', 'tab', 'esc', 'up', 'down', 'left', 'right',
    'page up', 'page down', 'home', 'end', 'delete'
}
MODIFIERS_ALL = {
    'ctrl', 'left ctrl', 'right ctrl', 'alt', 'left alt', 'right alt',
    'windows', 'left windows', 'right windows'
}

WM_INPUTLANGCHANGEREQUEST = 0x0050
LANG_EN = 0x0409
LANG_UKR = 0x0422
LANG_RU = 0x0419

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.PostMessageW.restype = wintypes.BOOL

# --- БЕЗПЕЧНА РОБОТА З БУФЕРОМ ОБМІНУ WINDOWS ---
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HANDLE
kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalFree.argtypes = [wintypes.HANDLE]
kernel32.GlobalFree.restype = wintypes.HANDLE
user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
user32.IsClipboardFormatAvailable.restype = wintypes.BOOL


def get_clipboard_text():
    for _ in range(10):
        if user32.OpenClipboard(None):
            try:
                handle = user32.GetClipboardData(CF_UNICODETEXT)
                if handle:
                    ptr = kernel32.GlobalLock(handle)
                    if ptr:
                        text = ctypes.c_wchar_p(ptr).value
                        kernel32.GlobalUnlock(handle)
                        return text or ""
            finally:
                user32.CloseClipboard()
            return ""
        time.sleep(0.02)
    return ""


def set_clipboard_text(text):
    if text is None:
        text = ""
    for attempt in range(10):
        if user32.OpenClipboard(None):
            try:
                user32.EmptyClipboard()
                if text:
                    buffer = ctypes.create_unicode_buffer(text)
                    size = ctypes.sizeof(buffer)
                    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
                    if handle:
                        ptr = kernel32.GlobalLock(handle)
                        if ptr:
                            ctypes.memmove(ptr, buffer, size)
                            kernel32.GlobalUnlock(handle)
                            # ВИПРАВЛЕНО: Якщо успішно, Windows забирає handle.
                            # Ми очищаємо його тільки у випадку невдачі. Жодного else!
                            if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                                kernel32.GlobalFree(handle)
                        else:
                            kernel32.GlobalFree(handle)
            finally:
                user32.CloseClipboard()
            return True
        time.sleep(0.02)
    return False


# --- WINDOWS API ХЕЛПЕРИ ---
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


def get_active_process_name(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h_process = kernel32.OpenProcess(0x1000, False, pid)
    if h_process:
        buffer = ctypes.create_unicode_buffer(260)
        size = wintypes.DWORD(260)
        if kernel32.QueryFullProcessImageNameW(h_process, 0, buffer, ctypes.byref(size)):
            kernel32.CloseHandle(h_process)
            return os.path.basename(buffer.value).lower()
        kernel32.CloseHandle(h_process)
    return ""


def get_window_title(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value.lower()


def send_hardware_keyup(vk_code, extended=False):
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_ulonglong)]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", INPUT_UNION)]

    flags = 0x0002
    if extended:
        flags |= 0x0001
    inp = INPUT(type=1, u=INPUT_UNION(ki=KEYBDINPUT(wVk=vk_code, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def release_all_modifiers():
    vks = [
        (0x10, False), (0xA0, False), (0xA1, False),
        (0x11, False), (0xA2, False), (0xA3, True),
        (0x12, False), (0xA4, False), (0xA5, True),
        (0x5B, True), (0x5C, True)
    ]
    for vk, ext in vks:
        send_hardware_keyup(vk, ext)


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
        self.root = tk.Tk()
        self.root.withdraw()
        self.ui_queue = queue.Queue()

        self.current_buffer = ""

        # ВИПРАВЛЕНО: Використовуємо Lock замість булевого прапорця
        self.switch_lock = threading.Lock()

        self.cycle_sequence = []
        self.cycle_index = 0
        self.current_hotkey = "f8"

        self.modifier_down_time = 0
        self.combo_pressed = False
        self.just_switched = False
        self.last_f8_time = 0
        self.last_key_time = 0

        self.saved_clipboard = None

        self.last_hwnd = 0
        self.active_app_name = ""

        self.load_or_create_config()

        threading.Thread(target=self.window_monitor_thread, daemon=True).start()
        mouse.on_click(self.reset_buffer)
        keyboard.hook(self.process_key)

        self.check_ui_queue()

    def run(self):
        self.root.mainloop()

    def window_monitor_thread(self):
        while True:
            current_hwnd = user32.GetForegroundWindow()
            if current_hwnd and current_hwnd != self.last_hwnd:
                self.last_hwnd = current_hwnd
                self.active_app_name = get_active_process_name(current_hwnd)
                self.reset_buffer()
            time.sleep(0.5)

    def check_ui_queue(self):
        try:
            msg = self.ui_queue.get_nowait()
            if msg == "show_settings":
                self.change_hotkey_runtime()
        except queue.Empty:
            pass
        self.root.after(100, self.check_ui_queue)

    def reset_buffer(self):
        self.current_buffer = ""
        self.cycle_sequence = []
        self.just_switched = False
        self.last_key_time = 0

    def is_heavy_3d_software(self):
        smart_apps = [app.replace('.exe', '') for app in SMART_HEURISTIC_APPS]
        for app in smart_apps:
            if app in self.active_app_name:
                return True
        win_title = get_window_title(self.last_hwnd)
        smart_apps.append('3ds max')
        for app in smart_apps:
            if app in win_title:
                return True
        return False

    def is_text_editing_likely(self):
        buf_len = len(self.current_buffer)
        recent_activity = max(self.last_key_time, self.last_f8_time)
        if buf_len >= 2 and (time.time() - recent_activity) < 5.5:
            return True
        if buf_len == 1 and (time.time() - recent_activity) < 1.5:
            return True
        return False

    def process_key(self, event):
        if not event.name:
            return
        name_lower = event.name.lower()

        if event.event_type == keyboard.KEY_UP:
            if name_lower == 'right ctrl':
                send_hardware_keyup(0xA3, extended=True)
            elif name_lower == 'right alt':
                send_hardware_keyup(0xA5, extended=True)

        # ВИПРАВЛЕНО: Перевіряємо статус Lock
        if self.active_app_name in IGNORE_APPS or self.switch_lock.locked():
            return

        if name_lower == 'f8' and event.event_type == keyboard.KEY_DOWN:
            if keyboard.is_pressed('ctrl') and (
                    keyboard.is_pressed('windows') or keyboard.is_pressed('left windows') or keyboard.is_pressed(
                'right windows')):
                self.ui_queue.put("show_settings")
                return

        if name_lower == self.current_hotkey:
            should_switch = self.is_text_editing_likely() if self.is_heavy_3d_software() else True

            if self.current_hotkey in MODIFIERS_ALL:
                if event.event_type == keyboard.KEY_DOWN:
                    if self.modifier_down_time == 0:
                        self.modifier_down_time = time.time()
                        self.combo_pressed = False
                elif event.event_type == keyboard.KEY_UP:
                    if self.modifier_down_time != 0 and not self.combo_pressed:
                        if time.time() - self.modifier_down_time < 0.5 and should_switch:
                            # ВИПРАВЛЕНО: Намагаємось безпечно захопити потоковий лок
                            if self.switch_lock.acquire(blocking=False):
                                threading.Thread(target=self.switch_layout, daemon=True).start()
                    self.modifier_down_time = 0
            else:
                if event.event_type == keyboard.KEY_DOWN and should_switch:
                    # ВИПРАВЛЕНО: Захоплення потокового локу
                    if self.switch_lock.acquire(blocking=False):
                        threading.Thread(target=self.switch_layout, daemon=True).start()
            return

        if event.event_type != keyboard.KEY_DOWN:
            return

        if 'shift' not in name_lower:
            self.combo_pressed = True

        if len(name_lower) == 1:
            if keyboard.is_pressed('ctrl') or keyboard.is_pressed('alt') or keyboard.is_pressed(
                    'windows') or keyboard.is_pressed('left windows') or keyboard.is_pressed('right windows'):
                self.reset_buffer()
                return

        if name_lower in ['shift', 'left shift', 'right shift', 'caps lock']:
            return

        if len(name_lower) == 1 or name_lower == 'space' or name_lower == 'backspace':
            if self.just_switched:
                self.current_buffer = ""
                self.just_switched = False
            self.cycle_sequence = []

        if len(name_lower) == 1:
            self.current_buffer += event.name
            self.last_key_time = time.time()
            if len(self.current_buffer) > MAX_BUFFER_LENGTH:
                self.current_buffer = self.current_buffer[-MAX_BUFFER_LENGTH:]
        elif name_lower == 'space':
            self.current_buffer += ' '
            self.last_key_time = time.time()
            if len(self.current_buffer) > MAX_BUFFER_LENGTH:
                self.current_buffer = self.current_buffer[-MAX_BUFFER_LENGTH:]
        elif name_lower == 'backspace':
            self.current_buffer = self.current_buffer[:-1]
            self.last_key_time = time.time()
        elif name_lower in RESET_KEYS:
            self.reset_buffer()

    def switch_layout(self):
        try:
            release_all_modifiers()
            time.sleep(0.01)
            now = time.time()

            is_in_cycle = (now - self.last_f8_time < 3.0) and len(self.cycle_sequence) > 0
            selected_text = ""

            # 1. ЗАХИСТ БУФЕРА: Зберігаємо оригінальний буфер ТІЛЬКИ якщо це перший натиск
            if not is_in_cycle:
                if user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                    self.saved_clipboard = get_clipboard_text()
                else:
                    self.saved_clipboard = None

            # 2. РОЗУМНИЙ CTRL+C
            if not is_in_cycle and (not self.current_buffer or (now - self.last_key_time > 1.5)):
                set_clipboard_text("")
                keyboard.press('ctrl')
                time.sleep(0.01)
                keyboard.send('c')
                time.sleep(0.01)
                keyboard.release('ctrl')

                for _ in range(10):
                    time.sleep(0.02)
                    selected_text = get_clipboard_text()
                    if selected_text:
                        break

            # --- Внутрішня функція ---
            def build_sequence(text_to_convert):
                eng_c = sum(1 for c in text_to_convert if c in ENG_SET)
                cyr_c = sum(1 for c in text_to_convert if c in CYR_SET)
                base_keys = text_to_convert if eng_c >= cyr_c else text_to_convert.translate(cyrillic_to_eng)

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

                seq = []
                seen_texts = set()
                for item_text, lang_id in raw_sequence:
                    if get_hkl_for_language(lang_id) is not None:
                        if item_text not in seen_texts:
                            seen_texts.add(item_text)
                            seq.append((item_text, lang_id))
                if not seq: seq.append((base_keys, LANG_EN))
                return seq

            # --------------------------

            target_text = ""

            if selected_text and isinstance(selected_text, str) and selected_text.strip():
                # === РЕЖИМ 2 (Виділений текст) ===
                if not is_in_cycle:
                    self.cycle_sequence = build_sequence(selected_text)
                    self.cycle_index = 0
                else:
                    self.cycle_index = (self.cycle_index + 1) % len(self.cycle_sequence)

                fixed_text, target_lang_id = self.cycle_sequence[self.cycle_index]
                target_text = fixed_text

                # Записуємо і перевіряємо, що запис вдався
                set_clipboard_text(fixed_text)
                for _ in range(10):
                    if get_clipboard_text() == fixed_text: break
                    time.sleep(0.01)

                keyboard.press('ctrl')
                time.sleep(0.01)
                keyboard.send('v')
                time.sleep(0.01)
                keyboard.release('ctrl')

                set_system_layout(get_hkl_for_language(target_lang_id))

                self.current_buffer = ""
                self.last_f8_time = now
                self.last_key_time = now
                self.just_switched = True

            elif self.current_buffer:
                # === РЕЖИМ 1 (Текст, який щойно набрали) ===
                if not is_in_cycle:
                    self.cycle_sequence = build_sequence(self.current_buffer)
                    self.cycle_index = 0
                else:
                    self.cycle_index = (self.cycle_index + 1) % len(self.cycle_sequence)

                fixed_text, target_lang_id = self.cycle_sequence[self.cycle_index]
                buffer_length = len(self.current_buffer)
                target_text = fixed_text

                # Оптимізоване видалення з необхідною для Windows мікропаузою!
                for _ in range(buffer_length):
                    keyboard.send('backspace')
                    time.sleep(0.005)

                set_clipboard_text(fixed_text)
                for _ in range(10):
                    if get_clipboard_text() == fixed_text: break
                    time.sleep(0.01)

                keyboard.press('ctrl')
                time.sleep(0.01)
                keyboard.send('v')
                time.sleep(0.01)
                keyboard.release('ctrl')

                set_system_layout(get_hkl_for_language(target_lang_id))

                self.current_buffer = fixed_text
                self.last_f8_time = now
                self.last_key_time = now
                self.just_switched = True

            # ФОНОВЕ ВІДНОВЛЕННЯ БУФЕРА ОБМІНУ
            if self.saved_clipboard is not None and target_text:
                def background_restore(expected, original):
                    # Даємо цільовій програмі 0.7 секунд на зчитування Ctrl+V
                    time.sleep(0.7)
                    if get_clipboard_text() == expected:
                        set_clipboard_text(original)

                threading.Thread(target=background_restore, args=(target_text, self.saved_clipboard),
                                 daemon=True).start()

        finally:
            release_all_modifiers()
            # ВИПРАВЛЕНО: Обов'язково звільняємо лок після завершення процедури!
            self.switch_lock.release()

    # --- ГРАФІЧНИЙ ІНТЕРФЕЙС ТА НАЛАШТУВАННЯ ---
    def ask_user_for_hotkey(self, initial_value="f8"):
        result_key = initial_value
        result_startup = is_in_startup()
        saved = False

        top = tk.Toplevel(self.root)
        top.title("Flip8 - Налаштування")
        top.geometry("360x420")
        top.resizable(False, False)
        top.attributes("-topmost", True)

        top.update_idletasks()
        width = top.winfo_width()
        height = top.winfo_height()
        x = (top.winfo_screenwidth() // 2) - (width // 2)
        y = (top.winfo_screenheight() // 2) - (height // 2)
        top.geometry('{}x{}+{}+{}'.format(width, height, x, y))

        chosen_key = tk.StringVar(value=initial_value)
        tk.Label(top, text="Оберіть гарячу клавішу\nдля перемикання розкладки:", font=("Segoe UI", 11, "bold"),
                 pady=15).pack()

        options = [
            ("Клавіша F8 (Рекомендовано)", "f8"),
            ("Клавіша Pause", "pause"),
            ("Клавіша Caps Lock", "caps lock"),
            ("Правий Ctrl", "right ctrl"),
            ("Правий Alt", "right alt")
        ]

        frame = tk.Frame(top)
        frame.pack(pady=5)
        for text, val in options:
            rb = tk.Radiobutton(frame, text=text, variable=chosen_key, value=val, font=("Segoe UI", 10), cursor="hand2")
            rb.pack(anchor="w", pady=2)

        startup_var = tk.BooleanVar(value=result_startup)
        tk.Checkbutton(top, text="Запускати автоматично з Windows", variable=startup_var,
                       font=("Segoe UI", 10, "italic"), cursor="hand2").pack(pady=10)

        def on_save():
            nonlocal result_key, result_startup, saved
            result_key = chosen_key.get()
            result_startup = startup_var.get()
            saved = True
            top.destroy()

        def on_closing():
            nonlocal result_key, result_startup, saved
            result_key = initial_value
            result_startup = is_in_startup()
            saved = False
            top.destroy()

        tk.Button(top, text="Зберегти", command=on_save, font=("Segoe UI", 10, "bold"), bg="#0078D7", fg="white",
                  width=20, cursor="hand2").pack(pady=5)
        tk.Label(top, text="(Це меню завжди можна викликати\nкомбінацією Ctrl + Win + F8)", font=("Segoe UI", 8),
                 fg="gray").pack(side="bottom", pady=10)
        top.protocol("WM_DELETE_WINDOW", on_closing)
        self.root.wait_window(top)
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
            chosen_key, run_on_startup, saved = self.ask_user_for_hotkey(initial_value="f8")
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
            pass

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
            messagebox.showinfo("Flip8", "Налаштування успішно збережено!", parent=self.root)


if __name__ == "__main__":
    app = Flip8App()
    app.run()
