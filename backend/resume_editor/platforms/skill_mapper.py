"""
BOSS Skill codes mapping utilities
Similar to industry_mapper.py but for programming/technical skills
Used to map local skill names to BOSS API skill codes during back-write
"""


def build_skill_name_code_map(skill_tree):
    """Build skill name -> code mapping dictionary
    
    Args:
        skill_tree: List of skill nodes from BOSS API
                    e.g., [{code: "800123", name: "Python"}, ...]
    
    Returns:
        Dictionary: {skill_name: skill_code}
    """
    m = {}
    for node in (skill_tree or []):
        if isinstance(node, dict):
            name = str(node.get("name", "")).strip()
            code = node.get("code")
            if name and code:
                m[name] = code
    return m


def map_skills(skills_input, skill_tree):
    """Map skill names to skill codes
    
    Args:
        skills_input: List of skills in various formats
                     - ['Python', 'JavaScript'] (strings)
                     - [{'name': 'Python'}, {'name': 'JavaScript'}] (objects)
        skill_tree: List of skill config from BOSS API
        
    Returns:
        Tuple: (codes_list, unmapped_list)
               - codes_list: List of skill codes as strings
               - unmapped_list: Names that couldn't be mapped
    """
    m = build_skill_name_code_map(skill_tree)
    codes = []
    unmapped = []
    
    for item in (skills_input or []):
        # Handle both string and object formats
        if isinstance(item, dict):
            nm = str(item.get("name", "")).strip()
        else:
            nm = str(item or "").strip()
        
        if not nm:
            continue
        
        if nm in m:
            codes.append(str(m[nm]))
        else:
            unmapped.append(nm)
    
    # Limit to first 6 (BOSS UI constraint)
    return codes[:6], unmapped[:6]


# Example usage/test
if __name__ == "__main__":
    mock_skill_tree = [
        {"code": "800123", "name": "Python"},
        {"code": "800456", "name": "JavaScript"},
        {"code": "800789", "name": "Docker"},
        {"code": "800111", "name": "React"},
        {"code": "800333", "name": "Node.js"},
        {"code": "800444", "name": "Kubernetes"},
    ]
    
    test_skills = [
        {"name": "Python"},
        {"name": "JavaScript"},
        "Docker",  # String format too
    ]
    
    codes, unmapped = map_skills(test_skills, mock_skill_tree)
    print(f"Codes: {codes}")  # Should output: ['800123', '800456', '800789']
    print(f"Unmapped: {unmapped}")  # Should output: []
    
    # Test with unmapped skills
    test_skills_fail = ["PHP", "UnknownSkill"]
    codes_fail, unmapped_fail = map_skills(test_skills_fail, mock_skill_tree)
    print(f"\nFail test:")
    print(f"Codes: {codes_fail}")  # []
    print(f"Unmapped: {unmapped_fail}")  # ['PHP', 'UnknownSkill']
