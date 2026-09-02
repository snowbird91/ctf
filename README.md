# snowbird91 CTF Hub

Personal Jekyll site for my security projects, CTF write-ups, and notes. The design is a neon, hacker-inspired skin on top of the Serial Programmer theme, with dark/light modes and accent neon highlights.

## Structure

| Path                             | Purpose                                                   |
| -------------------------------- | --------------------------------------------------------- |
| `pages/`                         | Top-level static pages (home, about, blog, etc.)          |
| `write-ups/<slug>/`              | One folder per write-up with its Markdown + assets        |
| `blog/<slug>/`                   | One folder per general blog post                           |
| `assets/`                        | CSS/JS/theme assets (icons, scripts, shared styles)       |

## Local Development

```bash
bundle install
bundle exec jekyll serve
```

Visit `http://127.0.0.1:4000/` by default (adjust for your `baseurl`).

## Customizing

- Edit `_data/author.yml` for bio, social links, and quote.
- Update `pages/` markdown files for site sections.
- Add blog posts under `blog/<slug>/` and challenge write-ups under `write-ups/<slug>/`.
- Add assets or tweak styles in `assets/css` and `assets/js`.

## Deployment

Designed for GitHub Pages: the repository builds with `baseurl: ""`. You can deploy anywhere Jekyll runs (Netlify, Cloudflare Pages, etc.).
