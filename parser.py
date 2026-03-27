import json
import re
import os

def parse_anomalies(md_path):
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find Global Anomalies
    global_section = re.search(r'## Global Anomalies.*?\n(.*?)\n---', content, re.DOTALL)
    global_anomalies = []
    if global_section:
        table = global_section.group(1)
        matches = re.findall(r'\| \*\*(.*?)\*\* \| (.*?) \| (.*?) \|', table)
        for name, desc, report in matches:
            global_anomalies.append({
                "name": name.strip(),
                "description": desc.strip(),
                "type": "Global",
                "report": report.strip()
            })

    # Find Maps and Rooms
    maps = {}
    # Split by map headers (excluding All Anomalies Reference)
    map_sections = re.split(r'\n## (?!Global|Sources|All)(.*?)\n', content)
    
    # map_sections[0] is everything before first map
    for i in range(1, len(map_sections), 2):
        map_name = map_sections[i].strip()
        map_content = map_sections[i+1]
        
        maps[map_name] = {"Rooms": {}}
        
        # Split by room headers
        room_sections = re.split(r'\n### (.*?)\n', map_content)
        for j in range(1, len(room_sections), 2):
            room_name = room_sections[j].strip()
            room_content = room_sections[j+1]
            
            anomalies = []
            # Parse table rows
            table_matches = re.findall(r'\| (.*?) \| (.*?) \| (.*?) \|', room_content)
            for name, attr_type, desc in table_matches:
                if name.strip().startswith('---') or name.strip().lower() == 'anomaly':
                    continue
                
                # Check for bold name or intruder (different markdown styles in the file)
                clean_name = name.strip().replace('**', '')
                anomalies.append({
                    "name": clean_name,
                    "type": attr_type.strip().replace('**', ''),
                    "description": desc.strip()
                })
            
            if anomalies:
                maps[map_name]["Rooms"][room_name] = anomalies

    return {
        "Global": global_anomalies,
        "Maps": maps
    }

if __name__ == "__main__":
    working_dir = os.path.dirname(os.path.abspath(__file__))
    md_file = os.path.join(working_dir, "..", "anomalies.md")
    output_file = os.path.join(working_dir, "anomalies_master.json")
    
    data = parse_anomalies(md_file)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    
    print(f"Parsed {len(data['Global'])} global anomalies and {len(data['Maps'])} maps.")
