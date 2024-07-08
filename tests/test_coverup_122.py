# file scalene/scalene_parseargs.py:40-416
# lines [43, 44, 46, 47, 48, 49, 50, 51, 70, 71, 81, 82, 83, 84, 85, 86, 88, 89, 90, 91, 92, 93, 95, 96, 97, 98, 99, 100, 102, 103, 104, 105, 106, 107, 108, 110, 111, 112, 113, 114, 115, 116, 117, 118, 120, 121, 122, 123, 124, 125, 126, 127, 128, 130, 131, 132, 133, 134, 135, 136, 138, 139, 140, 141, 142, 143, 144, 146, 147, 148, 149, 150, 151, 152, 154, 155, 156, 157, 158, 159, 160, 162, 163, 164, 165, 166, 167, 168, 170, 171, 172, 173, 174, 175, 176, 178, 179, 180, 181, 182, 184, 185, 186, 187, 188, 189, 190, 192, 193, 194, 195, 196, 197, 198, 200, 201, 202, 203, 204, 205, 206, 207, 208, 210, 211, 212, 215, 216, 217, 218, 220, 221, 222, 223, 224, 225, 226, 228, 229, 230, 231, 232, 233, 234, 236, 237, 238, 240, 242, 243, 244, 245, 246, 247, 249, 250, 251, 253, 255, 256, 257, 258, 259, 260, 262, 263, 264, 266, 268, 269, 270, 271, 272, 273, 274, 276, 277, 278, 279, 280, 281, 283, 284, 285, 286, 287, 288, 290, 291, 292, 293, 294, 295, 297, 298, 299, 300, 301, 302, 305, 306, 307, 308, 309, 310, 312, 313, 314, 315, 316, 317, 318, 319, 321, 322, 323, 324, 325, 326, 327, 329, 331, 332, 333, 334, 335, 337, 338, 341, 342, 345, 346, 347, 348, 349, 350, 354, 357, 358, 359, 360, 361, 364, 365, 366, 367, 368, 369, 370, 371, 372, 373, 374, 375, 376, 377, 379, 380, 384, 385, 386, 387, 388, 391, 392, 393, 395, 397, 398, 402, 403, 404, 405, 406, 407, 408, 410, 411, 416]
# branches ['46->47', '46->49', '210->211', '210->215', '329->331', '329->341', '357->358', '357->360', '364->365', '364->384', '365->366', '365->379', '384->385', '384->391', '385->386', '385->387', '387->388', '387->395', '402->403', '402->405', '405->406', '405->416', '407->408', '407->410', '410->411', '410->416']

import os
import sys
import pytest
from unittest.mock import patch
from scalene.scalene_parseargs import ScaleneParseArgs

# Define a test function to improve coverage
@pytest.fixture
def temp_script(tmp_path):
    # Create a temporary file to simulate a Python script
    temp_script = tmp_path / "temp_script.py"
    temp_script.write_text("print('Hello, world!')")
    return temp_script

def test_scalene_parseargs_full_coverage(temp_script):
    # Mock sys.argv to simulate command-line arguments
    test_args = [
        "scalene",
        "--version",
        str(temp_script),
        "---",
        "--some-arg",
    ]

    with patch.object(sys, "argv", test_args), \
         patch.object(sys, "exit") as mock_exit:
        # Call the parse_args method to test the argument parsing
        args, left = ScaleneParseArgs.parse_args()

    # Assertions to verify postconditions
    mock_exit.assert_called_once_with(-1)

    # Clean up by removing the temporary file
    temp_script.unlink()
