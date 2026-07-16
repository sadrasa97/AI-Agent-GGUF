# test.py - ماشین حساب پایتون
from calculator import Calculator

class Calculator:
    def __init__(self):
        self.result = 0
        
    def add(self, num1, num2):
        return num1 + num2
    
    def subtract(self, num1, num2):
        return num1 - num2
    
    def multiply(self, num1, num2):
        return num1 * num2
    
    def divide(self, num1, num2):
        if num2 == 0:
            raise ValueError("مخرج صفر نیست!")
        return num1 / num2

def main():
    calculator = Calculator()
    
    print("ماشین حساب پایتون")
    print("=" * 30)
    
    # تست محاسبات ساده
    test_cases = [
        (2, 5),
        (4, 7),
        (1, 0),
        (10, 2),
        (-3, 4),
        (1.5, 2)
    ]
    
    for i in range(len(test_cases)):
        a = test_cases[i][0]
        b = test_cases[i][1]
        
        print(f"حاصل: {a} + {b}")
        result = calculator.add(a, b)
        print(f"  -> {result}")
    
    # تست محاسبات پیچیده
    complex_test_cases = [
        (3 * 4),
        (5 - 2),
        (10 / 2 + 3),
        ((7 + 8) * 9) // 6,
        (-10 % 5)
    ]
    
    for i in range(len(complex_test_cases)):
        a = complex_test_cases[i][0]
        b = complex_test_cases[i][1]
        
        print(f"حاصل: {a} * {b}")
        result = calculator.multiply(a, b)
        print(f"  -> {result}")

if __name__ == "__main__":
    main()