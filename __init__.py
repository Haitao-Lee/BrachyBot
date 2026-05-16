"""
BrachyBot - AI-BrachyAgent System Package
=========================================
LLM-driven closed-loop brachytherapy planning system.
"""

__version__ = "1.0.0"
__author__ = "Ruijin Hospital AI Research Team"

import os
import sys

_BRACHYBOT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BRACHYBOT_ROOT)