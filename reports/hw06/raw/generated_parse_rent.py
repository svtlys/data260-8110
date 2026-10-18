import re
import pytest

def parse_rent(text: str) -> int:
    """
    Convert a rent string into an integer number of dollars per month.
    
    Args:
        text: A string representing rent, e.g., '$2,400/mo' or '2400 per month'.
        
    Returns:
        int: The rent amount in dollars per month.
        
    Raises:
        ValueError: If the text cannot be parsed into a valid rent amount.
    """
    cleaned_text = re.sub(r'[^\d\,\$\s]', '', text)
    parts = re.split(r'[\s,]+', cleaned_text)
    numeric_part = ''.join(part for part in parts if part.isdigit())
    unit_part = ''.join(part for part in parts if re.match(r'[a-zA-Z]+', part))
    
    if any(unit.lower() in unit_part.lower() for unit in ['mo', 'month']) and numeric_part:
        try:
            return int(numeric_part.replace(',', ''))
        except ValueError:
            raise ValueError("Invalid numeric value in rent string.")
    else:
        raise ValueError("Invalid rent format. Expected a numeric value followed by 'mo' or 'month'.")

def test_parse_rent_valid():
    assert parse_rent('$2,400/mo') == 2400
    assert parse_rent('2400 per month') == 2400
    assert parse_rent('3,500 mo') == 3500
    assert parse_rent('5000/month') == 5000

def test_parse_rent_invalid():
    with pytest.raises(ValueError):
        parse_rent('2400 mo')
    with pytest.raises(ValueError):
        parse_rent('2400 per year')
    with pytest.raises(ValueError):
        parse_rent('2400 mo$')

def test_parse_rent_edge_case():
    with pytest.raises(ValueError):
        parse_rent('2400')
    with pytest.raises(ValueError):
        parse_rent('2400 mo 123')
    with pytest.raises(ValueError):
        parse_rent('2400 mo $')

