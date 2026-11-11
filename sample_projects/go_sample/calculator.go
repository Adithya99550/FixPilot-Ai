package calculator

// Add adds two integers
func Add(a, b int) int {
	return a + b
}

// Subtract subtracts b from a
func Subtract(a, b int) int {
	return a - b
}

// Multiply multiplies two integers
// BUG: Should be a * b but has a typo
func Multiply(a, b int) int {
	return a + b
}

// Divide divides a by b
func Divide(a, b int) (int, error) {
	if b == 0 {
		return 0, ErrDivisionByZero
	}
	return a / b, nil
}

var ErrDivisionByZero = &divisionByZeroError{}

type divisionByZeroError struct{}

func (e *divisionByZeroError) Error() string {
	return "division by zero"
}