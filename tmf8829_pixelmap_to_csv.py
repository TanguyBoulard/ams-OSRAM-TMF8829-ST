# *****************************************************************************
# * Copyright by ams OSRAM AG                                                 *
# * All rights are reserved.                                                  *
# *                                                                           *
# *FOR FULL LICENSE TEXT SEE LICENSES-MIT.TXT                                 *
# *****************************************************************************

"""
Convert a TMF8829 JSON measurement file to pixel-map CSV files.

Produces two CSV files:
  - <basename>_results.csv : row, column, noise, xtalk, distance/snr/signal per peak
  - <basename>_histograms.csv : row, column, bin0..binN per pixel

Usage:
    python tmf8829_pixelmap_to_csv.py input.json [output_prefix]

If output_prefix is not provided, it defaults to the input filename without extension.
"""

import sys
import json
import csv
from typing import Dict, List, Optional, Tuple

# fp_mode value -> (rows, columns, bins_per_histogram)
FP_MODE_MAP = {
    0: {"name": "8x8A",  "rows": 8,  "cols": 8,  "bins": 256},
    1: {"name": "8x8B",  "rows": 8,  "cols": 8,  "bins": 256},
    2: {"name": "16x16", "rows": 16, "cols": 16, "bins": 64},
    3: {"name": "32x32", "rows": 32, "cols": 32, "bins": 64},
    4: {"name": "32x32s","rows": 32, "cols": 32, "bins": 64},
    5: {"name": "48x32", "rows": 32, "cols": 48, "bins": 64},
}


def load_json(filepath: str) -> dict:
    """Load a TMF8829 JSON measurement file."""
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


def get_fp_mode(data: dict) -> int:
    """Extract fp_mode from JSON configuration section.

    Returns:
        int: fp_mode value (0-5)

    Raises:
        KeyError: if fp_mode is not found in the configuration
    """
    try:
        return data["configuration"]["measure_cfg"]["fp_mode"]
    except KeyError:
        raise KeyError(
            "Cannot find 'fp_mode' in configuration.measure_cfg. "
            "Make sure the JSON file contains the sensor configuration."
        )


def get_resolution(fp_mode: int) -> Tuple[int, int, int, str]:
    """Get resolution parameters from fp_mode.

    Returns:
        Tuple of (rows, cols, bins_per_histogram, mode_name)
    """
    if fp_mode not in FP_MODE_MAP:
        raise ValueError(
            f"Unknown fp_mode={fp_mode}. Expected 0-5. "
            f"Valid modes: {list(FP_MODE_MAP.keys())}"
        )
    info = FP_MODE_MAP[fp_mode]
    return info["rows"], info["cols"], info["bins"], info["name"]


def detect_peak_fields(result_set: List[dict]) -> Tuple[int, bool]:
    """Detect the number of peaks and whether signal field is present.

    Scans the first frame's first pixel to determine the structure.

    Returns:
        Tuple of (nr_peaks, has_signal)
    """
    for frame in result_set:
        if "results" not in frame:
            continue
        for row in frame["results"]:
            for pixel in row:
                if "peaks" not in pixel or len(pixel["peaks"]) == 0:
                    continue
                nr_peaks = len(pixel["peaks"])
                has_signal = "signal" in pixel["peaks"][0]
                return nr_peaks, has_signal
    return 1, False


def build_results_header(nr_peaks: int, has_noise: bool, has_xtalk: bool,
                         has_signal: bool) -> List[str]:
    """Build the CSV header row for results."""
    header = ["frame", "row", "column"]
    if has_noise:
        header.append("noise")
    if has_xtalk:
        header.append("xtalk")
    for i in range(nr_peaks):
        header.append(f"distance{i}_mm")
        header.append(f"snr{i}")
        if has_signal:
            header.append(f"signal{i}")
    return header


def detect_optional_fields(result_set: List[dict]) -> Tuple[bool, bool]:
    """Detect if noise and xtalk fields are present in results."""
    for frame in result_set:
        if "results" not in frame:
            continue
        for row in frame["results"]:
            for pixel in row:
                has_noise = "noise" in pixel
                has_xtalk = "xtalk" in pixel
                return has_noise, has_xtalk
    return False, False


def write_results_csv(filepath: str, data: dict, fp_mode: int) -> str:
    """Write pixel results to a CSV file with row/column structure.

    Args:
        filepath: output CSV file path
        data: parsed JSON data
        fp_mode: focal plane mode

    Returns:
        Path to the written CSV file
    """
    rows, cols, _, mode_name = get_resolution(fp_mode)
    result_set = data.get("Result_Set", [])

    if not result_set:
        print("Warning: No Result_Set found in JSON data.")
        return filepath

    nr_peaks, has_signal = detect_peak_fields(result_set)
    has_noise, has_xtalk = detect_optional_fields(result_set)
    header = build_results_header(nr_peaks, has_noise, has_xtalk, has_signal)

    with open(filepath, "w", encoding="utf-8", newline="") as f:
        f.write(f"# fp_mode={fp_mode} ({mode_name}), resolution={cols}x{rows}, "
                f"peaks_per_pixel={nr_peaks}\n")
        writer = csv.writer(f)
        writer.writerow(header)

        for frame_idx, frame in enumerate(result_set):
            if "results" not in frame:
                continue

            pixel_idx = 0
            for row_data in frame["results"]:
                for pixel in row_data:
                    row_idx = pixel_idx // cols
                    col_idx = pixel_idx % cols

                    csv_row = [frame_idx, row_idx, col_idx]

                    if has_noise:
                        csv_row.append(pixel.get("noise", ""))
                    if has_xtalk:
                        csv_row.append(pixel.get("xtalk", ""))

                    peaks = pixel.get("peaks", [])
                    for i in range(nr_peaks):
                        if i < len(peaks):
                            peak = peaks[i]
                            distance_uq = peak.get("distance", 0)
                            distance_mm = distance_uq / 4.0
                            csv_row.append(f"{distance_mm:.2f}")
                            csv_row.append(peak.get("snr", ""))
                            if has_signal:
                                csv_row.append(peak.get("signal", ""))
                        else:
                            csv_row.append("")
                            csv_row.append("")
                            if has_signal:
                                csv_row.append("")

                    writer.writerow(csv_row)
                    pixel_idx += 1

    return filepath


def write_histograms_csv(filepath: str, data: dict, fp_mode: int) -> Optional[str]:
    """Write pixel histograms to a CSV file with row/column structure.

    Args:
        filepath: output CSV file path
        data: parsed JSON data
        fp_mode: focal plane mode

    Returns:
        Path to the written CSV file, or None if no histograms found
    """
    rows, cols, bins, mode_name = get_resolution(fp_mode)
    result_set = data.get("Result_Set", [])

    has_histograms = any("mp_histo" in frame for frame in result_set)
    if not has_histograms:
        return None

    header = ["frame", "row", "column"] + [f"bin{i}" for i in range(bins)]

    with open(filepath, "w", encoding="utf-8", newline="") as f:
        f.write(f"# fp_mode={fp_mode} ({mode_name}), resolution={cols}x{rows}, "
                f"bins_per_histogram={bins}\n")
        writer = csv.writer(f)
        writer.writerow(header)

        for frame_idx, frame in enumerate(result_set):
            if "mp_histo" not in frame:
                continue

            pixel_idx = 0
            for row_data in frame["mp_histo"]:
                for histogram in row_data:
                    row_idx = pixel_idx // cols
                    col_idx = pixel_idx % cols

                    bin_data = histogram.get("bin", [])
                    csv_row = [frame_idx, row_idx, col_idx] + list(bin_data)
                    writer.writerow(csv_row)
                    pixel_idx += 1

    return filepath


def convert(json_filepath: str, output_prefix: Optional[str] = None) -> None:
    """Main conversion function.

    Args:
        json_filepath: path to the input JSON file
        output_prefix: prefix for output CSV files (default: input name without .json)
    """
    if output_prefix is None:
        if json_filepath.endswith(".json"):
            output_prefix = json_filepath[:-5]
        else:
            output_prefix = json_filepath

    print(f"Loading {json_filepath} ...")
    data = load_json(json_filepath)

    fp_mode = get_fp_mode(data)
    rows, cols, bins, mode_name = get_resolution(fp_mode)
    print(f"Detected fp_mode={fp_mode} ({mode_name}): {cols} columns x {rows} rows")

    result_set = data.get("Result_Set", [])
    nb_frames = sum(1 for f in result_set if "results" in f)
    print(f"Found {nb_frames} result frame(s) in Result_Set")

    # Write results CSV
    results_csv = f"{output_prefix}_results.csv"
    write_results_csv(results_csv, data, fp_mode)
    print(f"Results written to {results_csv}")

    # Write histograms CSV
    histo_csv = f"{output_prefix}_histograms.csv"
    result = write_histograms_csv(histo_csv, data, fp_mode)
    if result:
        print(f"Histograms written to {histo_csv}")
    else:
        print("No histogram data found in JSON, skipping histogram CSV.")

    print("Done.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tmf8829_pixelmap_to_csv.py input.json [output_prefix]")
        print("  output_prefix: prefix for output files (default: input filename without .json)")
        print("  Produces: <prefix>_results.csv and <prefix>_histograms.csv")
        sys.exit(1)

    input_file = sys.argv[1]
    prefix = sys.argv[2] if len(sys.argv) > 2 else None
    convert(input_file, prefix)
