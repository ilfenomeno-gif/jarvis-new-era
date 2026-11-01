"""
PluginManager per Jarvis
========================
Carica dinamicamente tutti i plugin presenti nella cartella plugins/.

MIGLIORIE rispetto alla versione originale:
- Aggiunto plugins/__init__.py obbligatorio: senza di esso
  `importlib.import_module(f"plugins.{module_name}")` falliva con
  "No module named 'plugins'" su molte installazioni, perché pkgutil
  trovava i moduli ma import_module non riusciva a risolvere il
  pacchetto padre.
- Logging con livelli (info/errore) invece di semplici print, per
  distinguere a colpo d'occhio i problemi nei log.
- Il manager non si blocca più se `jarvis_core` non ha ancora
  l'attributo `accessibility`: i plugin che lo richiedono lo useranno
  comunque, ma il caricamento non esplode se manca (utile in fase di
  test/sviluppo isolato del PluginManager).
- Aggiunto un metodo `call(plugin_name, method_name, *args, **kwargs)`
  che centralizza le chiamate ai plugin con gestione eccezioni, così
  un errore in un singolo plugin non manda in crash tutto Jarvis.
- Aggiunto `reload_plugins()` per ricaricare i plugin a runtime senza
  riavviare Jarvis (utile in sviluppo).
"""

import importlib
import logging
import os
import pkgutil

logger = logging.getLogger("jarvis.plugin_manager")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[PluginManager] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class PluginManager:
    def __init__(self, jarvis_core, plugins_package="plugins"):
        self.jarvis = jarvis_core
        self.plugins_package = plugins_package
        self.plugins = {}
        self.load_plugins()

    def load_plugins(self):
        plugins_dir = self.plugins_package

        if not os.path.exists(plugins_dir):
            os.makedirs(plugins_dir)

        # Un pacchetto Python valido richiede __init__.py: lo creiamo
        # automaticamente se manca, per evitare l'errore
        # "No module named 'plugins'" al primo avvio.
        init_file = os.path.join(plugins_dir, "__init__.py")
        if not os.path.exists(init_file):
            open(init_file, "a").close()

        for _, module_name, is_pkg in pkgutil.iter_modules([plugins_dir]):
            if is_pkg:
                continue
            try:
                module = importlib.import_module(f"{self.plugins_package}.{module_name}")
                importlib.reload(module)  # garantisce codice aggiornato in reload_plugins()
                if hasattr(module, "register"):
                    plugin_instance = module.register(self.jarvis)
                    self.plugins[module_name] = plugin_instance
                    logger.info(f"Caricato con successo: {module_name}")
                else:
                    logger.error(
                        f"Il modulo {module_name} non espone una funzione register(jarvis): ignorato."
                    )
            except Exception as e:
                logger.error(f"Errore nel caricamento del plugin {module_name}: {e}")

    def reload_plugins(self):
        """Ricarica tutti i plugin a runtime (utile in sviluppo)."""
        self.plugins.clear()
        self.load_plugins()

    def call(self, plugin_name, method_name, *args, **kwargs):
        """
        Invoca in sicurezza un metodo di un plugin.
        Ritorna True/False in base al successo, e logga eventuali errori
        invece di far crashare tutto Jarvis per colpa di un plugin difettoso.
        """
        plugin = self.plugins.get(plugin_name)
        if plugin is None:
            logger.error(f"Plugin '{plugin_name}' non trovato o non caricato.")
            return False

        method = getattr(plugin, method_name, None)
        if method is None or not callable(method):
            logger.error(f"Il plugin '{plugin_name}' non ha il metodo '{method_name}'.")
            return False

        try:
            method(*args, **kwargs)
            return True
        except Exception as e:
            logger.error(f"Errore eseguendo {plugin_name}.{method_name}: {e}")
            return False

    def list_plugins(self):
        return list(self.plugins.keys())
