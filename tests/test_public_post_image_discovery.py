from app.services.source_images import (
    extract_public_image_url_from_html,
    is_public_facebook_content_url,
)


def test_public_facebook_post_url_allowed():

    assert is_public_facebook_content_url(
        "https://www.facebook.com/page/posts/123"
    )


def test_page_homepage_is_not_a_post():

    assert not is_public_facebook_content_url(
        "https://www.facebook.com/page"
    )


def test_extracts_fbcdn_og_image():

    html = """
    <html>
      <head>
        <meta
          property="og:image"
          content="https://scontent.xx.fbcdn.net/photo.jpg"
        >
      </head>
    </html>
    """

    image = extract_public_image_url_from_html(
        html,
        "https://www.facebook.com/page/posts/123",
    )

    assert (
        image
        == "https://scontent.xx.fbcdn.net/photo.jpg"
    )


def test_rejects_non_meta_image_host():

    html = """
    <meta
      property="og:image"
      content="https://example.com/photo.jpg"
    >
    """

    assert (
        extract_public_image_url_from_html(
            html,
            "https://www.facebook.com/page/posts/123",
        )
        is None
    )
