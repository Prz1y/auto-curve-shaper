"""
Frequency monitoring and measurement
"""
import re
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

from config import CLOCKS_SAMPLE_PS1, BURN_EXE, BASE_FREQUENCY
from utils import run_powershell, run_command

logger = logging.getLogger(__name__)


@dataclass
class FrequencyMeasurement:
    """Frequency measurement result"""
    timestamp: str
    ccd0_freq: float  # MHz
    ccd1_freq: float  # MHz
    all_cores: List[float]  # Per-core frequencies
    test_type: str  # "idle" or "load"
    duration: int  # seconds
    
    @property
    def avg_frequency(self) -> float:
        """Average frequency across all cores"""
        return sum(self.all_cores) / len(self.all_cores) if self.all_cores else 0.0
    
    @property
    def max_frequency(self) -> float:
        """Maximum frequency across all cores"""
        return max(self.all_cores) if self.all_cores else 0.0


def parse_clocks_output(output: str) -> Dict[str, List[float]]:
    """
    Parse clocks-sample.ps1 output
    Expected format: per-core frequencies in MHz
    """
    frequencies = []
    
    # Parse the PowerShell output
    # Looking for lines like: "Core 0: 4392 MHz"
    for line in output.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        
        # Try to extract frequency value
        match = re.search(r'(\d+(?:\.\d+)?)\s*MHz', line, re.IGNORECASE)
        if match:
            freq = float(match.group(1))
            frequencies.append(freq)
    
    # If we can't parse structured output, try to find any numbers that look like frequencies
    if not frequencies:
        numbers = re.findall(r'\b(\d{3,5})\b', output)
        frequencies = [float(n) for n in numbers if 1000 <= float(n) <= 10000]
    
    return {"frequencies": frequencies}


def measure_frequencies_idle(duration: int = 30) -> FrequencyMeasurement:
    """
    Measure CPU frequencies at idle
    """
    logger.info(f"Measuring idle frequencies for {duration} seconds...")
    
    from datetime import datetime
    
    try:
        output = run_powershell(CLOCKS_SAMPLE_PS1, args=[str(duration)], timeout=duration + 10)
        parsed = parse_clocks_output(output)
        frequencies = parsed.get("frequencies", [])
        
        if not frequencies:
            logger.warning("No frequencies parsed from clocks-sample output")
            # Return dummy data
            return FrequencyMeasurement(
                timestamp=datetime.now().isoformat(),
                ccd0_freq=0.0,
                ccd1_freq=0.0,
                all_cores=[],
                test_type="idle",
                duration=duration
            )
        
        # Assume first half is CCD0, second half is CCD1 (for dual-CCD CPUs)
        mid = len(frequencies) // 2
        ccd0_freq = sum(frequencies[:mid]) / mid if mid > 0 else 0.0
        ccd1_freq = sum(frequencies[mid:]) / (len(frequencies) - mid) if len(frequencies) > mid else 0.0
        
        result = FrequencyMeasurement(
            timestamp=datetime.now().isoformat(),
            ccd0_freq=ccd0_freq,
            ccd1_freq=ccd1_freq,
            all_cores=frequencies,
            test_type="idle",
            duration=duration
        )
        
        logger.info(f"Idle measurement: CCD0={ccd0_freq:.0f} MHz, CCD1={ccd1_freq:.0f} MHz, "
                   f"Avg={result.avg_frequency:.0f} MHz, Max={result.max_frequency:.0f} MHz")
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to measure idle frequencies: {e}")
        raise


def measure_frequencies_load(duration: int = 60) -> FrequencyMeasurement:
    """
    Measure CPU frequencies under full load
    """
    logger.info(f"Measuring load frequencies for {duration} seconds...")
    
    from datetime import datetime
    import subprocess
    import threading
    
    if not BURN_EXE.exists():
        raise FileNotFoundError(f"burn.exe not found at {BURN_EXE}")
    
    # Start burn in background
    logger.info("Starting burn.exe...")
    burn_process = subprocess.Popen(
        [str(BURN_EXE)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    try:
        # Wait a bit for burn to ramp up
        time.sleep(5)
        
        # Measure frequencies while burn is running
        output = run_powershell(CLOCKS_SAMPLE_PS1, args=[str(duration - 5)], timeout=duration)
        parsed = parse_clocks_output(output)
        frequencies = parsed.get("frequencies", [])
        
        if not frequencies:
            logger.warning("No frequencies parsed from clocks-sample output")
            return FrequencyMeasurement(
                timestamp=datetime.now().isoformat(),
                ccd0_freq=0.0,
                ccd1_freq=0.0,
                all_cores=[],
                test_type="load",
                duration=duration
            )
        
        # Assume first half is CCD0, second half is CCD1
        mid = len(frequencies) // 2
        ccd0_freq = sum(frequencies[:mid]) / mid if mid > 0 else 0.0
        ccd1_freq = sum(frequencies[mid:]) / (len(frequencies) - mid) if len(frequencies) > mid else 0.0
        
        result = FrequencyMeasurement(
            timestamp=datetime.now().isoformat(),
            ccd0_freq=ccd0_freq,
            ccd1_freq=ccd1_freq,
            all_cores=frequencies,
            test_type="load",
            duration=duration
        )
        
        logger.info(f"Load measurement: CCD0={ccd0_freq:.0f} MHz, CCD1={ccd1_freq:.0f} MHz, "
                   f"Avg={result.avg_frequency:.0f} MHz, Max={result.max_frequency:.0f} MHz")
        
        return result
        
    finally:
        # Stop burn
        logger.info("Stopping burn.exe...")
        burn_process.terminate()
        try:
            burn_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            burn_process.kill()
            burn_process.wait()


def run_stability_test(duration: int = 300) -> bool:
    """
    Run stability test
    Returns True if stable, False if crashed/errors detected
    """
    logger.info(f"Running stability test for {duration} seconds...")
    
    if not BURN_EXE.exists():
        raise FileNotFoundError(f"burn.exe not found at {BURN_EXE}")
    
    try:
        # Run burn.exe for specified duration
        result = run_command(
            [str(BURN_EXE)],
            timeout=duration,
            check=False
        )
        
        # Check for WHEA errors (would need to query event log)
        # For now, if burn completes without crash, consider it stable
        if result.returncode == 0:
            logger.info("Stability test PASSED")
            return True
        else:
            logger.warning(f"Stability test FAILED with return code {result.returncode}")
            return False
            
    except subprocess.TimeoutExpired:
        # Timeout means it ran for the full duration - this is good
        logger.info("Stability test PASSED (full duration)")
        return True
    except Exception as e:
        logger.error(f"Stability test FAILED with exception: {e}")
        return False


def check_whea_errors() -> int:
    """
    Check Windows Hardware Error Architecture (WHEA) event log
    Returns count of WHEA Event ID 19 errors since last check
    """
    try:
        # Query Windows Event Log for WHEA errors
        # Event ID 19 = processor core error (unstable voltage)
        cmd = [
            "powershell",
            "-Command",
            "Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-WHEA-Logger'; ID=19; StartTime=(Get-Date).AddMinutes(-10)} -ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count"
        ]
        
        result = run_command(cmd, check=False)
        count = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
        
        if count > 0:
            logger.warning(f"Detected {count} WHEA Event ID 19 errors")
        
        return count
        
    except Exception as e:
        logger.error(f"Failed to check WHEA errors: {e}")
        return 0
