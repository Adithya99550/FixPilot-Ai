package calculator

import (
	"testing"
)

func TestAdd(t *testing.T) {
	tests := []struct {
		name     string
		a, b     int
		expected int
	}{
		{"positive numbers", 2, 3, 5},
		{"negative and positive", -1, 1, 0},
		{"zeros", 0, 0, 0},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := Add(tt.a, tt.b)
			if result != tt.expected {
				t.Errorf("Add(%d, %d) = %d; want %d", tt.a, tt.b, result, tt.expected)
			}
		})
	}
}

func TestSubtract(t *testing.T) {
	if Subtract(5, 3) != 2 {
		t.Errorf("Subtract(5, 3) = %d; want 2", Subtract(5, 3))
	}
	if Subtract(0, 5) != -5 {
		t.Errorf("Subtract(0, 5) = %d; want -5", Subtract(0, 5))
	}
}

func TestMultiply(t *testing.T) {
	// This test will fail because Multiply has a bug (adds instead of multiplies)
	if Multiply(2, 3) != 6 {
		t.Errorf("Multiply(2, 3) = %d; want 6", Multiply(2, 3))
	}
	if Multiply(4, 5) != 20 {
		t.Errorf("Multiply(4, 5) = %d; want 20", Multiply(4, 5))
	}
	if Multiply(-2, 3) != -6 {
		t.Errorf("Multiply(-2, 3) = %d; want -6", Multiply(-2, 3))
	}
}

func TestDivide(t *testing.T) {
	result, err := Divide(10, 2)
	if err != nil {
		t.Errorf("Divide(10, 2) returned error: %v", err)
	}
	if result != 5 {
		t.Errorf("Divide(10, 2) = %d; want 5", result)
	}

	result, err = Divide(7, 2)
	if err != nil {
		t.Errorf("Divide(7, 2) returned error: %v", err)
	}
	if result != 3 {
		t.Errorf("Divide(7, 2) = %d; want 3", result)
	}
}

func TestDivideByZero(t *testing.T) {
	_, err := Divide(5, 0)
	if err == nil {
		t.Error("Divide(5, 0) should return an error")
	}
	if err != ErrDivisionByZero {
		t.Errorf("Divide(5, 0) returned wrong error: %v", err)
	}
}