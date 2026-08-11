"""测试 _clean_value() 函数的清理逻辑"""


def _clean_value(value: str) -> str:
    """清理配置值的首尾空白字符和引号"""
    return value.strip().strip('`"\' ')


def test_clean_value():
    """测试各种输入情况"""
    test_cases = [
        # (输入, 期望输出, 描述)
        ('https://gateway.foxfingerlab.com', 'https://gateway.foxfingerlab.com', '正常值'),
        (' https://gateway.foxfingerlab.com ', 'https://gateway.foxfingerlab.com', '首尾空格'),
        ('" https://gateway.foxfingerlab.com "', 'https://gateway.foxfingerlab.com', '引号+内部空格'),
        ('` https://gateway.foxfingerlab.com `', 'https://gateway.foxfingerlab.com', '反引号+内部空格'),
        ("' https://gateway.foxfingerlab.com '", 'https://gateway.foxfingerlab.com', '单引号+内部空格'),
        ('  "  https://gateway.foxfingerlab.com  "  ', 'https://gateway.foxfingerlab.com', '多层空格和引号'),
        ('" `https://gateway.foxfingerlab.com` "', 'https://gateway.foxfingerlab.com', '混合引号'),
    ]
    
    print("测试 _clean_value() 函数\n" + "="*60)
    
    all_passed = True
    for input_val, expected, desc in test_cases:
        result = _clean_value(input_val)
        passed = result == expected
        all_passed = all_passed and passed
        
        status = "✓" if passed else "✗"
        print(f"{status} {desc}")
        print(f"  输入:    '{input_val}'")
        print(f"  期望:    '{expected}'")
        print(f"  实际:    '{result}'")
        if not passed:
            print(f"  ❌ 不匹配!")
        print()
    
    print("="*60)
    if all_passed:
        print("✅ 所有测试通过!")
    else:
        print("❌ 部分测试失败!")
    
    return all_passed


if __name__ == '__main__':
    test_clean_value()
