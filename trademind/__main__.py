"""python3 -m trademind — Entry Point"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trademind.cli import main

main()
