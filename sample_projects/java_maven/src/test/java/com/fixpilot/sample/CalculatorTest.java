package com.fixpilot.sample;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class CalculatorTest {

    private final Calculator calculator = new Calculator();

    @Test
    void testAdd() {
        assertEquals(5, calculator.add(2, 3));
        assertEquals(0, calculator.add(-1, 1));
        assertEquals(0, calculator.add(0, 0));
    }

    @Test
    void testSubtract() {
        assertEquals(2, calculator.subtract(5, 3));
        assertEquals(-5, calculator.subtract(0, 5));
    }

    @Test
    void testMultiply() {
        // This test will fail because multiply has a bug (adds instead of multiplies)
        assertEquals(6, calculator.multiply(2, 3));
        assertEquals(20, calculator.multiply(4, 5));
        assertEquals(-6, calculator.multiply(-2, 3));
    }

    @Test
    void testDivide() {
        assertEquals(5, calculator.divide(10, 2));
        assertEquals(3, calculator.divide(7, 2));
    }

    @Test
    void testDivideByZero() {
        ArithmeticException exception = assertThrows(ArithmeticException.class, () -> {
            calculator.divide(5, 0);
        });
        assertEquals("Division by zero", exception.getMessage());
    }
}