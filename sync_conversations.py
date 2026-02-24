"""
Sincroniza conversaciones de Claude Code con el proyecto.

Uso:
    python sync_conversations.py backup    # Copia conversaciones al proyecto
    python sync_conversations.py restore   # Restaura conversaciones desde el proyecto
"""
import shutil
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
BACKUP_DIR = PROJECT_DIR / ".claude-conversations"
CLAUDE_DIR = Path.home() / ".claude" / "projects" / "c--Users-Nahuel-Desktop-Nueva-INFO-CCU"


def backup():
    """Copia conversaciones y memoria al proyecto."""
    if not CLAUDE_DIR.exists():
        print(f"No se encontro: {CLAUDE_DIR}")
        return 1

    BACKUP_DIR.mkdir(exist_ok=True)

    count = 0
    for f in CLAUDE_DIR.iterdir():
        if f.is_file():
            shutil.copy2(f, BACKUP_DIR / f.name)
            count += 1

    # Copiar memoria tambien
    memory_dir = CLAUDE_DIR / "memory"
    if memory_dir.exists():
        backup_memory = BACKUP_DIR / "memory"
        if backup_memory.exists():
            shutil.rmtree(backup_memory)
        shutil.copytree(memory_dir, backup_memory)
        count += sum(1 for _ in memory_dir.iterdir())

    print(f"Backup completado: {count} archivos copiados a {BACKUP_DIR}")
    return 0


def restore():
    """Restaura conversaciones y memoria desde el proyecto."""
    if not BACKUP_DIR.exists():
        print(f"No se encontro backup en: {BACKUP_DIR}")
        return 1

    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)

    count = 0
    for f in BACKUP_DIR.iterdir():
        if f.is_file():
            shutil.copy2(f, CLAUDE_DIR / f.name)
            count += 1

    # Restaurar memoria
    backup_memory = BACKUP_DIR / "memory"
    if backup_memory.exists():
        memory_dir = CLAUDE_DIR / "memory"
        memory_dir.mkdir(exist_ok=True)
        for f in backup_memory.iterdir():
            if f.is_file():
                shutil.copy2(f, memory_dir / f.name)
                count += 1

    print(f"Restore completado: {count} archivos restaurados a {CLAUDE_DIR}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("backup", "restore"):
        print("Uso: python sync_conversations.py [backup|restore]")
        sys.exit(1)

    sys.exit(backup() if sys.argv[1] == "backup" else restore())
