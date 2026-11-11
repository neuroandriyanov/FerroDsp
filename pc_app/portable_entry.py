"""Frozen entry point: retain a diagnostic log even without a console."""
import bootstrap
import ctypes
import logging
import sys
import traceback

def main():
    try:
        import multiprocessing
        multiprocessing.freeze_support()
        bootstrap.LOCAL.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler
        handler = RotatingFileHandler(bootstrap.LOCAL/'application.log', maxBytes=1_000_000,
                                      backupCount=2, encoding='utf-8')
        logging.basicConfig(handlers=[handler], level=logging.WARNING,
                            format='%(asctime)s %(levelname)s %(message)s')
        import app
        return app.main()
    except Exception:
        detail = traceback.format_exc()
        logging.error(detail)
        if '--self-test' not in sys.argv:
            ctypes.windll.user32.MessageBoxW(None,
                'Не удалось запустить FerroDSP Lab. Распакуйте весь архив в доступную для записи папку.\n'
                f'Журнал: {bootstrap.LOCAL / "application.log"}\n\n{detail[-1800:]}', 'FerroDSP Lab', 0x10)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
