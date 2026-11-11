const { add, subtract, multiply, divide } = require('./calculator');

describe('Calculator', () => {
  test('adds two numbers', () => {
    expect(add(2, 3)).toBe(5);
    expect(add(-1, 1)).toBe(0);
    expect(add(0, 0)).toBe(0);
  });

  test('subtracts two numbers', () => {
    expect(subtract(5, 3)).toBe(2);
    expect(subtract(0, 5)).toBe(-5);
  });

  test('multiplies two numbers', () => {
    // This test will fail because multiply has a bug (adds instead of multiplies)
    expect(multiply(2, 3)).toBe(6);
    expect(multiply(4, 5)).toBe(20);
    expect(multiply(-2, 3)).toBe(-6);
  });

  test('divides two numbers', () => {
    expect(divide(10, 2)).toBe(5);
    expect(divide(7, 2)).toBe(3.5);
  });

  test('throws on division by zero', () => {
    expect(() => divide(5, 0)).toThrow('Division by zero');
  });
});