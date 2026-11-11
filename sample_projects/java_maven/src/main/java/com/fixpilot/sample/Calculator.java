package com.fixpilot.sample;

public class Calculator {
    // Add two integers
    public int add(int a, int b) {
        return a + b;
    }

    // Subtract b from a
    public int subtract(int a, int b) {
        return a - b;
    }

    // Multiply two integers
    // BUG: Should be a * b but has a typo
    public int multiply(int a, int b) {
        return a + b;
    }

    // Divide a by b
    public int divide(int a, int b) {
        if (b == 0) {
            throw new ArithmeticException("Division by zero");
        }
        return a / b;
    }
}