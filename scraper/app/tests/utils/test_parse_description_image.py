from app.utils.parse_description_image import parse_description_image


class TestParseDescriptionImage:
    """Test suite for parse_description_image function."""

    def test_simple_image_tag(self):
        html = '<html><body><img src="https://example.com/image.jpg"></body></html>'
        result = parse_description_image(html)
        assert result == "https://example.com/image.jpg"

    def test_multiple_images_returns_first(self):
        html = """
 <p><img src="https://www.sta.si/foto/800,800,8,1483816" class="type:primaryImage" alt="foto"/></p><p>Kanadski premier Mark Carney je danes petkov pogovor s kitajskim predsednikom Xi Jinpingom ob robu vrha foruma Apec označil za točko preobrata pri obnavljanju načetih odnosov med državama. Obenem je potrdil, da se je ameriškemu predsedniku Donaldu Trumpu opravičil za oglas proti carinam, ki je Trumpa spodbudil k višjim carinam za Kanado.</p>
        """
        result = parse_description_image(html)
        assert result == "https://www.sta.si/foto/800,800,8,1483816"

    def test_no_image_tag(self):
        html = "<html><body><p>No image here</p></body></html>"
        result = parse_description_image(html)
        assert result is None

    def test_empty_string(self):
        result = parse_description_image("")
        assert result is None
