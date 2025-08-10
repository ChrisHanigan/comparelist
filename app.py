import os
import sqlite3
import click # Import click for CLI commands
from flask import Flask, request, render_template, url_for, redirect, g

app = Flask(__name__)

# Select database based on environment variable (testing of production)|
if os.environ.get('TESTING') == 'True':
    DATABASE = 'test_items.db'
    app.config['DATABASE'] = DATABASE # Also set in app.config for consistency if needed elsewhere
else:
    DATABASE = 'items.db'
    app.config['DATABASE'] = DATABASE

# Store full path
app.config['DATABASE_PATH'] = os.path.join(os.path.dirname(__file__), DATABASE) 

#Connect database
def get_db_connection():
    """Gets a database connection. The connection is associated with the application context."""
    if 'db' not in g:
        # Ensure the directory exists if DATABASE includes a path (though not strictly needed here)
        # db_path = app.config['DATABASE_PATH']
        # os.makedirs(os.path.dirname(db_path), exist_ok=True)
        # g.db = sqlite3.connect(db_path)

        # Connect using the DATABASE name relative to the app's root path
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        app.logger.debug(f"Database connection opened to {DATABASE}")
    return g.db

def close_db(e=None):
    """Closes the database connection."""
    db = g.pop('db', None)
    if db is not None:
        db.close()
        app.logger.debug(f"Database connection closed for {DATABASE}")

# Use teardown_appcontext instead of teardown_request
app.teardown_appcontext(close_db)

def init_db_logic():
    """Core logic to initialize the database. Separated for clarity."""
    db = get_db_connection() # Get connection managed by Flask context
    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
    try:
        with open(schema_path) as f:
            db.executescript(f.read())
        db.commit()
        # No db.close() here! Let teardown_appcontext handle it.
    except FileNotFoundError:
        # Use click.echo for CLI feedback, app.logger for app logs
        click.echo(f"Error: schema.sql not found at {schema_path}", err=True)
        app.logger.error(f"schema.sql not found at {schema_path}")
        raise # Re-raise the exception so the command fails clearly
    except sqlite3.Error as e:
        click.echo(f"Error initializing database: {e}", err=True)
        app.logger.error(f"Error initializing database: {e}")
        db.rollback() # Rollback on error
        raise # Re-raise
    except Exception as e:
        click.echo(f"An unexpected error occurred during init_db: {e}", err=True)
        app.logger.error(f"An unexpected error occurred during init_db: {e}")
        db.rollback()
        raise # Re-raise

# Register the init-db command
@app.cli.command('init-db')  # Decorator to register the command
def init_db_command():       # The function Flask calls for 'init-db'
    """Clear existing data and create new tables."""
    try:
        init_db_logic()      # Call the function containing the actual logic
        click.echo(f"Initialized the database '{app.config.get('DATABASE', 'UNKNOWN')}'.") # Use app.config
    except Exception:
         import sys
         sys.exit(1) # Exit with error code if init_db_logic failed



# --- Routes  ---

@app.before_request
def before_request():
    """Ensures that a database connection is available before each request."""
    # This is technically redundant if all routes call get_db_connection(),
    # but doesn't hurt.
    get_db_connection()

@app.route('/compare', methods=['GET'])
def compare_items():
    """Compares two random items."""
    conn = get_db_connection()
    try:
        items = conn.execute('SELECT id, name FROM items ORDER BY RANDOM() LIMIT 2').fetchall()
        if len(items) == 2:
            return render_template('compare.html', item1=items[0], item2=items[1])
        else:
            # Check if items table exists but is empty
            item_count_row = conn.execute("SELECT count(id) FROM items").fetchone()
            if item_count_row and item_count_row[0] < 2:
                 return "Not enough items in the database to compare (need at least 2)."
            else: # Should not happen if RANDOM() works, but defensive coding
                 return "Could not fetch two distinct items."
    except sqlite3.OperationalError as e:
         app.logger.error(f"Database error in /compare: {e}")
         if "no such table: items" in str(e):
             return "Database not initialized. Run 'flask init-db' first.", 500
         return f"Database error: {e}", 500

@app.route('/record_comparison', methods=['POST'])
def record_comparison():
    """Records a comparison between two items."""
    conn = get_db_connection()
    try:
        item1_id = request.form['item1_id']
        item2_id = request.form['item2_id']
        preference = int(request.form['preference']) # Ensure preference is integer

        conn.execute('INSERT INTO comparisons (item1_id, item2_id, score) VALUES (?, ?, ?)',
                     (item1_id, item2_id, preference))
        conn.commit()
    except (KeyError, ValueError) as e:
        app.logger.warning(f"Invalid form data for comparison: {e}")
        conn.rollback()
        # Consider flashing a message to the user
        # flash("Invalid data submitted for comparison.")
    except sqlite3.IntegrityError as e:
        app.logger.warning(f"Integrity error during comparison insert: {e}")
        conn.rollback()
        # flash("Could not record comparison due to a database constraint.")
    except sqlite3.OperationalError as e:
         app.logger.error(f"Database error in /record_comparison: {e}")
         return f"Database error: {e}. Did you run 'flask init-db'?", 500
    except Exception as e:
        app.logger.error(f"Unexpected error in /record_comparison: {e}")
        conn.rollback()
        return "An unexpected error occurred.", 500

    return redirect(url_for('index'))


def calculate_relative_rank(item_id):
    """Calculates the relative rank of an item based on comparisons."""
    conn = get_db_connection()
    total_score = 0
    try:
        # Ensure item_id is treated as an integer if it's numeric in the DB
        item_id_int = int(item_id)
        comparisons = conn.execute(
            'SELECT score, item1_id, item2_id FROM comparisons WHERE item1_id = ? OR item2_id = ?',
            (item_id_int, item_id_int)).fetchall()

        for comparison in comparisons:
            # Ensure comparison IDs are also treated as integers for comparison
            comp_item1_id = int(comparison['item1_id'])
            comp_item2_id = int(comparison['item2_id'])

            if comp_item1_id == item_id_int:
                # Ensure score is numeric before adding
                total_score += int(comparison['score'])
            elif comp_item2_id == item_id_int:
                # Ensure score is numeric before negating
                total_score -= int(comparison['score'])

    except sqlite3.OperationalError as e:
        app.logger.warning(f"Database error calculating rank for item {item_id}: {e}")
        return 0 # Return a default rank or handle appropriately
    except (ValueError, TypeError) as e:
        app.logger.warning(f"Invalid data format during rank calculation for item {item_id}: {e}")
        return 0
    except Exception as e:
        app.logger.error(f"Unexpected error calculating rank for item {item_id}: {e}")
        return 0 # Default rank on unexpected error

    return total_score


@app.route('/', methods=['GET', 'POST'])
def index():
    """Displays a list of items, ranked."""
    conn = get_db_connection()
    if request.method == 'POST':
        item_name = request.form.get('item_name') # Use .get for safety
        if item_name and item_name.strip(): # Basic validation: ensure name is not empty/whitespace
            try:
                conn.execute('INSERT INTO items (name) VALUES (?)', (item_name.strip(),))
                conn.commit()
            except sqlite3.OperationalError as e:
                 app.logger.error(f"Database error adding item in /: {e}")
                 return f"Database error: {e}. Did you run 'flask init-db'?", 500
            except Exception as e:
                 app.logger.error(f"Unexpected error adding item in /: {e}")
                 conn.rollback()
                 return "An unexpected error occurred while adding the item.", 500
        else:
            # Optionally, provide feedback if the name is empty
            # flash('Item name cannot be empty.')
            pass # Or handle as needed
        return redirect(url_for('index')) # Redirect even if POST fails or is empty

    # GET request part
    ranked_items = []
    try:
        items_data = conn.execute('SELECT id, name FROM items').fetchall()
        for item in items_data:
            rank = calculate_relative_rank(item['id'])
            ranked_items.append({'id': item['id'], 'name': item['name'], 'rank': rank})

        ranked_items.sort(key=lambda x: x['rank'], reverse=True)

    except sqlite3.OperationalError as e:
        app.logger.error(f"Database error fetching items in /: {e}")
        if "no such table: items" in str(e):
             return "Database not initialized. Run 'flask init-db' first.", 500
        else:
             return f"Database error: {e}", 500
    except Exception as e:
        app.logger.error(f"Unexpected error fetching items in /: {e}")
        return "An unexpected error occurred while fetching items.", 500

    return render_template('index.html', items=ranked_items)
# Add this function to your app.py

@app.route('/database')
def view_database():
    """Displays the raw contents of the database tables."""
    conn = get_db_connection()
    # Fetch all items, ordered by ID for consistency
    all_items = conn.execute('SELECT id, name FROM items ORDER BY id').fetchall()
    # Fetch all comparisons, ordered for consistency
    all_comparisons = conn.execute('SELECT item1_id, item2_id, score FROM comparisons ORDER BY item1_id, item2_id').fetchall()
    conn.close()
    
    # Pass the fetched data to a new template
    return render_template('database_view.html', items=all_items, comparisons=all_comparisons)



# Remove the main() function and the if __name__ == '__main__': block
# They are not needed when using `flask run` and `flask init-db`
# def main():
#    """Main function to initialize the database and run the application."""
#    # Initialization is now handled by `flask init-db`
#    # if not os.path.exists(DATABASE):
#    #    init_db_logic() # Call logic directly if needed, but CLI is better
#    app.run(debug=True)
#
# if __name__ == '__main__':
#    main()

