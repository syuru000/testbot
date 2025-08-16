import sqlite3

class Item:
    def __init__(self, id, name, description, item_type, effect_type, effect_value, stackable, max_stack, effect_name=None):
        self.id = id
        self.name = name
        self.description = description
        self.item_type = item_type
        self.effect_type = effect_type
        self.effect_value = effect_value
        self.stackable = bool(stackable) # SQLite stores BOOLEAN as INTEGER (0 or 1)
        self.max_stack = max_stack
        self.effect_name = effect_name

    def __str__(self):
        return f"{self.name} (ID: {self.id}, Type: {self.item_type})"

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "item_type": self.item_type,
            "effect_type": self.effect_type,
            "effect_value": self.effect_value,
            "stackable": self.stackable,
            "max_stack": self.max_stack,
            "effect_name": self.effect_name
        }

class ItemManager:
    def __init__(self, db_path='game.db'):
        self.db_path = db_path
        self.items = {} # Stores Item objects by their ID

    def load_items_from_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT id, name, description, item_type, effect_type, effect_value, stackable, max_stack, effect_name FROM items")
        rows = c.fetchall()
        conn.close()

        for row in rows:
            item = Item(*row)
            self.items[item.id] = item
            print(f"Loaded item: {item.name}") # For debugging

    def get_item(self, item_id):
        return self.items.get(item_id)

    def get_item_by_name(self, item_name):
        for item_id, item in self.items.items():
            if item.name.lower() == item_name.lower():
                return item
        return None

# Example usage (for testing)
if __name__ == '__main__':
    # Ensure database is set up with items
    from database import setup_database
    setup_database()

    item_manager = ItemManager()
    item_manager.load_items_from_db()

    # Test retrieving items
    potion = item_manager.get_item_by_name("기초 회복 물약")
    if potion:
        print(f"Found: {potion.name}, Effect: {potion.effect_type} {potion.effect_value}")

    pickaxe = item_manager.get_item_by_name("낡은 곡괭이")
    if pickaxe:
        print(f"Found: {pickaxe.name}, Type: {pickaxe.item_type}")
