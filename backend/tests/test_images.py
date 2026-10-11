from app.utils.images import detect_image_extension

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
JPG = b"\xff\xd8\xff\xe0" + b"0" * 20
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 20


def test_real_images_are_recognised():
    assert detect_image_extension(PNG) == ".png"
    assert detect_image_extension(JPG) == ".jpg"
    assert detect_image_extension(WEBP) == ".webp"


def test_other_files_are_rejected():
    assert detect_image_extension(b"MZ\x90\x00 this is an exe") is None
    assert detect_image_extension(b"<svg onload='alert(1)'></svg>") is None
    assert detect_image_extension(b"GIF89a....") is None
    assert detect_image_extension(b"") is None
    assert detect_image_extension(b"RIFF\x00\x00\x00\x00WAVE") is None
