# SiloSight - Local Visual Asset Management Engine

SiloSight is a complete, single-file Windows/cross-platform desktop application that acts as a local visual asset management engine. The app allows users to index local directories, automatically tag images using an offline ResNet-50 AI model, manually manage metadata, filter with advanced search parameters, and interact with the results via a polished, modern dark-mode graphical interface.

## Tech Stack
- **GUI Framework**: CustomTkinter (modern dark-mode GUI)
- **Database**: SQLite3 (Standard Library)
- **Image Processing**: PIL (Pillow)
- **AI Framework**: Hugging Face Transformers (using `microsoft/resnet-50` for local, offline classification)
- **Programming Language**: Python 3

---

## Key Features

1. **Directory Management & Privacy Control**:
   - Easily add or remove tracked folders using graphical dialogs.
   - Prominent toggle switch: **\"Save directories across sessions (Privacy Mode)\"**.
   - When disabled (Privacy Mode enabled), folder paths are kept purely in volatile runtime memory and immediately purged from the SQLite database.

2. **Background Indexer & Database Pruning**:
   - A background thread indexes folders asynchronously, keeping the GUI responsive.
   - Extracts system creation/modification timestamps.
   - Skips corrupted images silently.
   - Passes new images through the local Hugging Face classification pipeline (`microsoft/resnet-50`) to collect labels with confidence > 0.1.
   - **\"Prune Dead Files\"** utility scans the database and purges records of files that have been deleted or moved from disk.

3. **Advanced Search & Filter Panel**:
   - Supports multi-word queries (comma or space separated) using SQL `AND` logic across both AI-generated and custom user tags (e.g., \"dog, park\" requires matches to contain both keywords).
   - Dynamically sort results by \"Newest First\" or \"Oldest First\".
   - Toggle \"Favorites Only\" to show only starred images.

4. **Visual Previews & Native Interaction**:
   - Displays a list of file paths matching the search criteria.
   - Selecting a file displays a dynamically scaled thumbnail preview (up to 200x200 max) in the side editor panel while preserving aspect ratio.
   - Double-clicking any image in the list opens the file in the default native system photo viewer (`os.startfile()` on Windows, falling back to `xdg-open` / `open` on Linux/macOS).

5. **Manual Metadata & Batch Tagging Controls**:
   - **Single Selection**: Displays read-only AI auto-tags, an editable text box for custom user tags, and a star/unstar toggle.
   - **Batch Selection** (Ctrl/Shift-click): Switches the editor panel into bulk actions mode, allowing users to append or overwrite custom user tags, and favorite/unfavorite all selected items simultaneously.

---

## Setup & Running

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/cf12craft/SiloSight.git
   cd SiloSight
   ```

2. **Install Dependencies**:
   ```bash
   pip install customtkinter transformers pillow torch
   ```

3. **Run the Application**:
   ```bash
   python app.py
   ```
