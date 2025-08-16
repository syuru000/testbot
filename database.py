import sqlite3

def setup_database():
    conn = sqlite3.connect('game.db')
    c = conn.cursor()

    # --- 테이블 구조 변경 및 생성 ---

    # players 테이블에 current_location_id 추가
    try:
        c.execute("ALTER TABLE players ADD COLUMN current_location_id INTEGER DEFAULT 1")
        print("players 테이블에 'current_location_id' 열이 추가되었습니다.")
    except sqlite3.OperationalError:
        pass # 이미 열이 존재하는 경우

    # players 테이블에 attack_buff_until 추가
    try:
        c.execute("ALTER TABLE players ADD COLUMN attack_buff_until REAL DEFAULT 0") # Unix timestamp
        print("players 테이블에 'attack_buff_until' 열이 추가되었습니다.")
    except sqlite3.OperationalError:
        pass # 이미 열이 존재하는 경우

    # players 테이블에 status_effect, status_effect_end_time, status_effect_value 추가
    try:
        c.execute("ALTER TABLE players ADD COLUMN status_effect TEXT DEFAULT NULL")
        c.execute("ALTER TABLE players ADD COLUMN status_effect_end_time REAL DEFAULT 0")
        c.execute("ALTER TABLE players ADD COLUMN status_effect_value INTEGER DEFAULT 0")
        print("players 테이블에 'status_effect', 'status_effect_end_time', 'status_effect_value' 열이 추가되었습니다.")
    except sqlite3.OperationalError:
        pass # 이미 열이 존재하는 경우

    # players 테이블에 새로운 스탯 필드 추가
    try:
        c.execute("ALTER TABLE players ADD COLUMN strength INTEGER DEFAULT 0")
        c.execute("ALTER TABLE players ADD COLUMN swordsmanship INTEGER DEFAULT 0")
        c.execute("ALTER TABLE players ADD COLUMN recovery INTEGER DEFAULT 0")
        c.execute("ALTER TABLE players ADD COLUMN observation INTEGER DEFAULT 0")
        c.execute("ALTER TABLE players ADD COLUMN water_magic INTEGER DEFAULT 0")
        c.execute("ALTER TABLE players ADD COLUMN sight INTEGER DEFAULT 0")
        print("players 테이블에 새로운 스탯 필드가 추가되었습니다.")
    except sqlite3.OperationalError:
        pass # 이미 열이 존재하는 경우

    # items 테이블에 effect_name 추가
    try:
        c.execute("ALTER TABLE items ADD COLUMN effect_name TEXT DEFAULT NULL")
        print("items 테이블에 'effect_name' 열이 추가되었습니다.")
    except sqlite3.OperationalError:
        pass # 이미 열이 존재하는 경우

    # items 테이블에 max_durability 추가
    try:
        c.execute("ALTER TABLE items ADD COLUMN max_durability INTEGER DEFAULT NULL")
        print("items 테이블에 'max_durability' 열이 추가되었습니다.")
    except sqlite3.OperationalError:
        pass # 이미 열이 존재하는 경우

    # player_inventory 테이블에 durability 추가
    try:
        c.execute("ALTER TABLE player_inventory ADD COLUMN durability INTEGER DEFAULT NULL")
        print("player_inventory 테이블에 'durability' 열이 추가되었습니다.")
    except sqlite3.OperationalError:
        pass # 이미 열이 존재하는 경우

    # 기존 맵 관련 테이블 삭제 (스키마 변경을 위해)
    c.execute("DROP TABLE IF EXISTS locations")
    c.execute("DROP TABLE IF EXISTS map_connections")
    c.execute("DROP TABLE IF EXISTS location_monsters")

    # locations 테이블 생성
    c.execute('''
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT NOT NULL,
            actions TEXT -- JSON string of available actions
        )
    ''')

    # map_connections 테이블 생성
    c.execute('''
        CREATE TABLE IF NOT EXISTS map_connections (
            from_location_id INTEGER NOT NULL,
            to_location_id INTEGER NOT NULL,
            FOREIGN KEY (from_location_id) REFERENCES locations(id),
            FOREIGN KEY (to_location_id) REFERENCES locations(id),
            PRIMARY KEY (from_location_id, to_location_id)
        )
    ''')

    # location_monsters 테이블 생성 (지역별 몬스터 정보)
    c.execute('''
        CREATE TABLE IF NOT EXISTS location_monsters (
            location_id INTEGER NOT NULL,
            monster_name TEXT NOT NULL,
            FOREIGN KEY (location_id) REFERENCES locations(id),
            PRIMARY KEY (location_id, monster_name)
        )
    ''')

    # 기존 테이블 (players, game_state, chat_logs) 생성 구문은 유지
    # players 테이블은 current_location_id 필드를 포함하여 재생성/수정합니다.
    c.execute('''
        CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            login_id TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            nickname TEXT UNIQUE,
            level INTEGER DEFAULT 1,
            hp INTEGER DEFAULT 100,
            mp INTEGER DEFAULT 50,
            gold INTEGER DEFAULT 0,
            exp INTEGER DEFAULT 0,
            current_location_id INTEGER DEFAULT 1,
            job TEXT DEFAULT '초보자',
            skp INTEGER DEFAULT 0
        )
    ''')

    # items 테이블 생성
    c.execute('''
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT NOT NULL,
            item_type TEXT NOT NULL, -- 'consumable', 'tool', 'equipment', 'material'
            effect_type TEXT,        -- 'hp_recovery', 'attack_boost', 'status_effect_apply', 'status_effect_cure', 'none'
            effect_name TEXT,        -- 상태 이상 이름 (예: 'poison', 'stun')
            effect_value INTEGER,    -- HP 회복량, 공격력 증가량, 상태 이상 지속 시간 등
            stackable BOOLEAN DEFAULT 0, -- 0 for False, 1 for True
            max_stack INTEGER DEFAULT 1,
            max_durability INTEGER DEFAULT NULL -- NULL for non-durable items
        )
    ''')

    # player_inventory 테이블 생성
    c.execute('''
        CREATE TABLE IF NOT EXISTS player_inventory (
            user_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            quantity INTEGER DEFAULT 1,
            durability INTEGER, -- NULL for non-durable items
            PRIMARY KEY (user_id, item_id),
            FOREIGN KEY (user_id) REFERENCES players(user_id),
            FOREIGN KEY (item_id) REFERENCES items(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS game_state (
            id INTEGER PRIMARY KEY DEFAULT 1,
            chat_message_id INTEGER,
            status_message_id INTEGER
        )
    ''')
    c.execute("INSERT OR IGNORE INTO game_state (id) VALUES (1)")

    c.execute('''
        CREATE TABLE IF NOT EXISTS chat_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            message TEXT NOT NULL
        )
    ''')

    # --- 초기 데이터 삽입 ---
    
    # locations 데이터
    locations_data = [
        (1, '평온한 초원', '부드러운 바람이 불어오는 시작의 장소입니다. 저 멀리 숲이 보입니다.', '["덤불 살피기", "나무 올라가기"]'),
        (2, '동쪽 숲', '나무가 빽빽하게 들어서 있어 어둡고 습합니다. 약한 몬스터들이 주로 나타납니다.', '["수풀 헤치기", "버섯 채집"]'),
        (3, '오래된 폐허', '과거에 무슨 일이 있었는지, 스산한 기운이 감도는 곳입니다. 강력한 몬스터가 있다는 소문이 있습니다.', '["문 두드리기", "잔해 뒤지기"]'),
        (4, '강가', '맑은 물이 흐르는 강가입니다. 물고기가 뛰어노는 모습이 보입니다.', '["낚시하기", "물 마시기"]'),
        (5, '어두운 동굴', '음침하고 습한 동굴입니다. 위험한 몬스터들이 서식합니다.', '["탐색하기", "광물 채집"]')
    ]
    c.executemany("INSERT OR IGNORE INTO locations (id, name, description, actions) VALUES (?, ?, ?, ?)", locations_data)

    # map_connections 데이터
    connections_data = [
        (1, 2), # 평온한 초원 -> 동쪽 숲
        (2, 1), # 동쪽 숲 -> 평온한 초원
        (2, 3), # 동쪽 숲 -> 오래된 폐허
        (3, 2),  # 오래된 폐허 -> 동쪽 숲
        (1, 4), # 평온한 초원 -> 강가
        (4, 1), # 강가 -> 평온한 초원
        (3, 5), # 오래된 폐허 -> 어두운 동굴
        (5, 3)  # 어두운 동굴 -> 오래된 폐허
    ]
    c.executemany("INSERT OR IGNORE INTO map_connections (from_location_id, to_location_id) VALUES (?, ?)", connections_data)

    # location_monsters 데이터
    monsters_data = [
        (2, '슬라임'),
        (2, '고블린'),
        (3, '고블린'),
        (3, '오크'),
        (4, '늑대'),
        (5, '거미'),
        (5, '오크')
    ]
    c.executemany("INSERT OR IGNORE INTO location_monsters (location_id, monster_name) VALUES (?, ?)", monsters_data)

    # items 데이터
    items_data = [
        (1, '기초 회복 물약', 'HP를 2 회복시켜주는 물약입니다.', 'consumable', 'hp_recovery', 2, 1, 99, None, None),
        (2, '명의의 약', 'HP를 10 회복시켜주는 귀한 약입니다.', 'consumable', 'hp_recovery', 10, 1, 99, None, None),
        (3, '낡은 곡괭이', '오래되어 녹슨 곡괭이입니다. 채광에 사용됩니다.', 'tool', 'none', None, 0, 1, None, 20),
        (4, '공격력 강화 물약', '공격력을 5분간 증가시켜주는 물약입니다.', 'consumable', 'attack_boost', 300, 0, 1, None, None),
        (5, '독 물약', '상대에게 독 상태 이상을 부여합니다.', 'consumable', 'status_effect_apply', 60, 0, 1, 'poison', None),
        (6, '생고기', '익히지 않은 날고기입니다. 요리 재료로 사용됩니다.', 'consumable', 'hp_recovery', 5, 1, 99, None, None), # 임시로 HP 회복 효과 부여
        (7, '낡은 낚싯대', '금방이라도 부러질 것 같은 낚싯대입니다.', 'tool', 'none', None, 0, 1, None, 15),
        (8, '돌멩이', '강가에서 흔히 볼 수 있는 돌멩이입니다.', 'material', 'none', None, 1, 99, None, None),
        (9, '철광석', '제련하면 철을 얻을 수 있는 광석입니다.', 'material', 'none', None, 1, 99, None, None),
        (10, '송사리', '작고 귀여운 물고기입니다. 먹을 수는 없어 보입니다.', 'material', 'none', None, 1, 99, None, None),
        (11, '잉어', '제법 살이 오른 잉어입니다. 요리하면 맛있을 것 같습니다.', 'consumable', 'hp_recovery', 10, 1, 99, None, None),
        (12, '나뭇가지', '가늘고 긴 나뭇가지입니다. 어디에든 쓸모가 있을 것 같습니다.', 'material', 'none', None, 1, 99, None, None),
        (13, '질긴 나뭇잎', '크고 질긴 나뭇잎입니다. 무언가를 엮는 데 사용될 수 있을 것 같습니다.', 'material', 'none', None, 1, 99, None, None),
        (14, '튼튼한 낚싯대', '꽤나 튼튼해 보이는 낚싯대입니다. 더 좋은 물고기를 낚을 수 있을 것 같습니다.', 'tool', 'none', None, 0, 1, None, 30),
        (15, '돌 칼', '돌을 뾰족하게 갈아 만든 칼입니다. 없는 것보다는 낫습니다.', 'equipment', 'attack_boost', 2, 0, 1, None, 20)
    ]
    c.executemany("INSERT OR IGNORE INTO items (id, name, description, item_type, effect_type, effect_value, stackable, max_stack, effect_name, max_durability) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", items_data)

    conn.commit()
    conn.close()

if __name__ == '__main__':
    setup_database()
    print("Database 'game.db' with map system tables is ready.")
