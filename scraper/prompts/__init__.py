"""
scraper/prompts - AI Prompt Builders
stage1_prompt: Candidate extraction and pre-classification prompt
stage2_prompt: Deep JD experience and compensation verification prompt
"""
from . import stage1_prompt
from . import stage2_prompt

# Backward compatibility aliases
stage1 = stage1_prompt
stage2 = stage2_prompt
