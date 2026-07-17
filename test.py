import tkinter as tk
from tkinter import ttk

class ModernCalculator:
    def __init__(self, root):
        self.root = root
        self.root.title("Modern Calculator")
        self.root.geometry("320x450")
        self.root.resizable(False, False)
        self.root.configure(bg="#1e1e2e")
        
        # Style configuration
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        self.expression = "0"
        
        # Create display
        self.display_var = tk.StringVar(value="0")
        self.display = tk.Entry(
            root,
            textvariable=self.display_var,
            font=("Segoe UI", 24, "bold"),
            justify="right",
            bd=0,
            bg="#2a2a3a",
            fg="#ffffff",
            insertbackground="#ffffff"
        )
        self.display.grid(row=0, column=0, columnspan=4, padx=15, pady=20, sticky="nsew", ipady=15)
        self.display.focus_set()
        
        # Button styling
        self.btn_config = {
            "font": ("Segoe UI", 16, "bold"),
            "bd": 0,
            "cursor": "hand2",
            "width": 4,
            "height": 1
        }
        
        # Button colors
        self.colors = {
            "number": {"bg": "#3a3a4a", "fg": "#ffffff", "active": "#4a4a5a"},
            "operator": {"bg": "#ff6b6b", "fg": "#ffffff", "active": "#ff8787"},
            "function": {"bg": "#4a4a5a", "fg": "#ffffff", "active": "#5a5a6a"},
            "equals": {"bg": "#4ecdc4", "fg": "#ffffff", "active": "#6bddd6"}
        }
        
        # Button layout
        self.buttons = [
            ("C", 1, 0, "function"), ("Â±", 1, 1, "function"), ("%", 1, 2, "function"), ("Ã·", 1, 3, "operator"),
            ("7", 2, 0, "number"), ("8", 2, 1, "number"), ("9", 2, 2, "number"), ("Ã", 2, 3, "operator"),
            ("4", 3, 0, "number"), ("5", 3, 1, "number"), ("6", 3, 2, "number"), ("-", 3, 3, "operator"),
            ("1", 4, 0, "number"), ("2", 4, 1, "number"), ("3", 4, 2, "number"), ("+", 4, 3, "operator"),
            ("â«", 5, 0, "function"), ("0", 5, 1, "number"), (".", 5, 2, "number"), ("=", 5, 3, "equals"),
        ]
        
        self.create_buttons()
        self.bind_keyboard()
        
    def create_buttons(self):
        for (text, row, col, btn_type) in self.buttons:
            btn = tk.Button(
                self.root,
                text=text,
                **self.btn_config,
                bg=self.colors[btn_type]["bg"],
                fg=self.colors[btn_type]["fg"],
                activebackground=self.colors[btn_type]["active"],
                activeforeground=self.colors[btn_type]["fg"],
                command=lambda t=text: self.on_button_click(t)
            )
            btn.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
            
            # Hover effect
            btn.bind("<Enter>", lambda e, b=btn: b.config(bg=self.colors[btn_type]["active"]))
            btn.bind("<Leave>", lambda e, b=btn: b.config(bg=self.colors[btn_type]["bg"]))
        
        # Configure grid weights for responsive buttons
        for i in range(6):
            self.root.grid_rowconfigure(i, weight=1)
        for i in range(4):
            self.root.grid_columnconfigure(i, weight=1)
    
    def on_button_click(self, char):
        if char == "C":
            self.clear_all()
        elif char == "â«":
            self.backspace()
        elif char == "Â±":
            self.negate()
        elif char == "%":
            self.percentage()
        elif char == "=":
            self.calculate()
        elif char == "Ã·":
            self.append("/")
        elif char == "Ã":
            self.append("*")
        else:
            self.append(char)
    
    def append(self, char):
        current = self.display_var.get()
        if current == "0" or current == "Error":
            self.display_var.set(char)
        else:
            self.display_var.set(current + char)
    
    def clear_all(self):
        self.display_var.set("0")
    
    def backspace(self):
        current = self.display_var.get()
        if current != "0" and current != "Error":
            new_value = current[:-1]
            self.display_var.set(new_value if new_value else "0")
    
    def negate(self):
        current = self.display_var.get()
        if current != "0" and current != "Error":
            if current.startswith("-"):
                self.display_var.set(current[1:])
            else:
                self.display_var.set("-" + current)
    
    def percentage(self):
        try:
            current = float(self.display_var.get())
            self.display_var.set(str(current / 100))
        except ValueError:
            self.display_var.set("Error")
    
    def calculate(self):
        try:
            expression = self.display_var.get()
            # Replace Ã and Ã· with proper operators
            expression = expression.replace("Ã", "*").replace("Ã·", "/")
            result = eval(expression)
            # Format result to avoid long decimals
            if result == int(result):
                result = int(result)
            self.display_var.set(str(result))
        except Exception:
            self.display_var.set("Error")
    
    def bind_keyboard(self):
        self.root.bind("<Key>", self.key_press)
    
    def key_press(self, event):
        key = event.keysym
        if key in "0123456789":
            self.append(key)
        elif key in "+-*/":
            self.append(key)
        elif key == "Return":
            self.calculate()
        elif key == "BackSpace":
            self.backspace()
        elif key == "Escape":
            self.clear_all()
        elif key == "period":
            self.append(".")


if __name__ == "__main__":
    root = tk.Tk()
    app = ModernCalculator(root)
    root.mainloop()
