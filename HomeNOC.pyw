"""Abre o HomeNOC sem a janela preta do terminal (duplo clique no Windows).

É o mesmo que rodar "python -m homenoc": o painel abre no navegador e o
monitoramento continua em segundo plano. Para encerrar, use Ajustes > Encerrar.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from homenoc.app import main

sys.exit(main(sys.argv[1:]))
