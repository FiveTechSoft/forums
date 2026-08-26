<?php
// Test upload - simple endpoint to verify deployment
header('Content-Type: text/plain');
echo "AI endpoint is alive! Time: " . date('c') . "\n";
echo "PHP version: " . phpversion() . "\n";
echo "Server software: " . ($_SERVER['SERVER_SOFTWARE'] ?? 'unknown') . "\n";
