// Simple calculator module with a bug
pub fn add(a: i32, b: i32) -> i32 {
    a + b
}

pub fn subtract(a: i32, b: i32) -> i32 {
    a - b
}

pub fn multiply(a: i32, b: i32) -> i32 {
    // BUG: Should be a * b but has a typo
    a + b
}

pub fn divide(a: i32, b: i32) -> Result<i32, &'static str> {
    if b == 0 {
        Err("division by zero")
    } else {
        Ok(a / b)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_add() {
        assert_eq!(add(2, 3), 5);
        assert_eq!(add(-1, 1), 0);
        assert_eq!(add(0, 0), 0);
    }

    #[test]
    fn test_subtract() {
        assert_eq!(subtract(5, 3), 2);
        assert_eq!(subtract(0, 5), -5);
    }

    #[test]
    fn test_multiply() {
        // This test will fail because multiply has a bug (adds instead of multiplies)
        assert_eq!(multiply(2, 3), 6);
        assert_eq!(multiply(4, 5), 20);
        assert_eq!(multiply(-2, 3), -6);
    }

    #[test]
    fn test_divide() {
        assert_eq!(divide(10, 2), Ok(5));
        assert_eq!(divide(7, 2), Ok(3));
    }

    #[test]
    fn test_divide_by_zero() {
        assert_eq!(divide(5, 0), Err("division by zero"));
    }
}