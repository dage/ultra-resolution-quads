def calculate_max_iter(level, base=2000, increment=200):
    """
    Calculates the maximum iterations for a given zoom level.
    Formula: max_iter = base + (level * increment)
    
    Args:
        level (int): The current zoom level.
        base (int): The base number of iterations at level 0. Default 2000.
        increment (int): The number of iterations to add per level. Default 200.
        
    Returns:
        int: The calculated maximum iterations.
    """
    return base + (int(level) * increment)
