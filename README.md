# Serial Programmer Blank Template

A clean starting point built on top of the Serial Programmer Jekyll theme. Demo posts, bios, screenshots, and funding links have been removed so you can plug in your own content immediately.

## What's Included

- Jekyll 4 configuration with SEO, sitemap, emoji, and feed plugins
- Empty posts collection (`all_collections/_posts/.keep`) waiting for your markdown files
- Responsive layouts with light/dark toggle, math support, syntax highlighting, and copy-to-clipboard buttons
- Minimal assets folder containing the CSS and JS the layouts expect

## Getting Started

1. Install dependencies
   ```bash
   bundle install
   ```
2. Run the local server
   ```bash
   bundle exec jekyll serve
   ```
3. Visit `http://localhost:4000` (or the host/port printed in your terminal) to preview.

## Customizing

- Update `_config.yml` for the site title, base URL, and feed metadata.
- Edit `_data/author.yml` to add your photo, bio, and any social links (leave `contact` empty to hide icons).
- Create new posts inside `all_collections/_posts/` following the `YYYY-MM-DD-title.md` convention.
- Replace or extend the CSS/JS inside `assets/` as needed for your brand.
- Swap the favicon or logos stored in `assets/icons` if you add new contact types.

## Deployment

This template works anywhere that can build or host a static Jekyll site (GitHub Pages, Netlify, Cloudflare Pages, etc.). For GitHub Pages user/organization sites you may need to remove `url`/`baseurl` from `_config.yml` depending on your repository layout.

## Credits

Based on the Serial Programmer theme. See `LICENSE` for attribution requirements.
