import sqlite3
from datetime import datetime, timedelta
import random

def init_database():
    conn = sqlite3.connect('fault_history.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS fault_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fault_type TEXT,
        occurrence_date TEXT,
        solution TEXT,
        downtime_hours REAL,
        equipment_id TEXT,
        CHECK(fault_type IN ('轴承异响', '温度异常', '振动异常', '液压系统故障'))
    )
    ''')
    
    # TODO 2: 准备数据
    fault_types = ['轴承异响', '温度异常', '振动异常', '液压系统故障']
    equipment_ids = ['EQ001', 'EQ002', 'EQ003']
    
    solutions = {
        '轴承异响': ['更换轴承', '加注润滑油', '调整轴承间隙'],
        '温度异常': ['清洗散热器', '更换冷却液', '检修冷却泵'],
        '振动异常': ['紧固螺栓', '更换减震垫', '动平衡校准'],
        '液压系统故障': ['更换液压油', '修复密封件', '清洗滤芯']
    }
    
    records = []
    base_date = datetime.now()
    
    for i in range(50):
        fault_type = random.choice(fault_types)
        days_ago = random.randint(0, 90)
        occurrence_date = (base_date- timedelta(days=days_ago)).strftime('%Y-%m-%d')
        solution = random.choice(solutions[fault_type])
        downtime_hours = round(random.uniform(0.5,8),1)
        equipment_id = random.choice(equipment_ids)
        record = (equipment_id, fault_type, occurrence_date, solution, downtime_hours)
        records.append(record)
    cursor.executemany("INSERT INTO fault_records(equipment_id, fault_type, occurrence_date, solution, downtime_hours) VALUES(?,?,?,?,?)",records)
    conn.commit()
    cursor.execute("SELECT COUNT(*) FROM fault_records")
    print(f"✅ 数据库初始化完成，共{cursor.fetchone()[0]}条记录")
    
    cursor.execute("""
        SELECT equipment_id, fault_type, COUNT(*) 
        FROM fault_records 
        GROUP BY equipment_id, fault_type
    """)
    print("\n📊 数据分布:")
    for row in cursor.fetchall():
        print(f"  {row[0]} - {row[1]}: {row[2]}条")
    
    conn.close()

if __name__ == '__main__':
    init_database()