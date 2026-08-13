#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lanceur silencieux : double-cliquer sur ce fichier ouvre l'application
sans faire apparaître de fenêtre noire de terminal à côté.
(Un fichier .pyw est ouvert par Windows avec pythonw.exe, sans console.)
"""
import os
import runpy

os.chdir(os.path.dirname(os.path.abspath(__file__)))
runpy.run_path("caisse_app.py", run_name="__main__")
