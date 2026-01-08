import json
import os
import re
import sys
from mimetypes import guess_type
from pathlib import Path
from urllib.parse import unquote, urlparse, urlsplit

import click
import cssutils
from bs4 import BeautifulSoup as Soup


def generate_hubspot_asset_url(original_path, profile=None, base_path="/"):
    """
    オリジナルのパスを新しいパターンに置換する関数。
    """
    original_path = str((Path(base_path) / original_path).resolve())

    if profile and "path_prefix" in profile:
        original_path = original_path.replace(profile["path_prefix"], "")

    original_path = original_path.replace("//", "/")
    THEME = os.environ["HUBSPOT_FOLDER"]
    public_path = f"{{{{get_asset_url('/{THEME}{original_path}') }}}}"
    return public_path


def change_url(original_url, profile=None, base_path="/"):
    if not original_url:
        return

    if original_url.startswith("tel:"):
        return
    if original_url.startswith("mailto:"):
        return
    if original_url.startswith("http"):
        # 絶対パスは変換しない(外部の可能性)
        parsed = urlparse(original_url)
        if parsed.netloc == os.environ.get("TARGET_CNAME", ""):
            original_url = parsed.path

        else:
            return

    changed = change_anchor_url_rule(original_url, profile=profile, base_path=base_path)
    if changed.startswith("{{"):
        return changed

    original_url = changed

    mt, _ = guess_type(original_url)
    if not mt or mt in ["text/html"]:
        return

    new_src = generate_hubspot_asset_url(original_url, profile=profile, base_path=base_path)

    return new_src


def change_assert_url_tag(asset_tag, profile=None, base_path="/"):
    tag_name = asset_tag.name

    if tag_name in ["a", "link"]:
        attr_name_set = ["href"]
    elif tag_name in ["source"]:
        attr_name_set = ["srcset"]
    else:
        attr_name_set = ["src", "srcset"]

    for attr_name in attr_name_set:
        original_src = asset_tag.get(attr_name)
        if not original_src:
            continue

        if attr_name == "srcset":
            new_srcset = []
            for entry in original_src.split(","):
                parts = entry.strip().split()
                if not parts:
                    continue
                descriptor = " ".join(parts[1:])
                new_src = change_url(parts[0], profile=profile, base_path=base_path)
                new_parts = new_src or parts[0]

                new_entry = f"{new_parts} {descriptor}" if descriptor else new_parts
                new_srcset.append(new_entry)
            new_src = ", ".join(new_srcset)
        else:
            new_src = change_url(original_src, profile=profile, base_path=base_path)
            if not new_src:
                continue

        asset_tag[attr_name] = new_src
        click.echo(f"置き換え:  {tag_name}.{attr_name}: {original_src} -> {new_src}")


def change_asset_url(soup, profile=None, base_path="/"):
    tags = ["img", "script", "link", "a", "source"]

    founds = soup.find_all(tags)
    if not founds:
        click.echo(f"{tags}:タグが見つかりませんでした。")
        return

    _ = [change_assert_url_tag(tag, profile=profile, base_path=base_path) for tag in founds]


def modify_by_rule(path, profile: dict):
    rules = profile.get("anchor_rules", None) or []
    for rule in rules:
        if re.search(rf"{rule[0]}", path):
            return re.sub(rf"{rule[0]}", rf"{rule[1]}", path)
    return path


def change_anchor_url_rule(href, profile: dict, base_path="/"):
    url = unquote(href)
    obj = urlsplit(url)
    path = str((Path(base_path) / obj.path).resolve())

    if href.startswith("mailto"):
        return href

    mtype, _ = guess_type(path)
    path = modify_by_rule(path, profile)
    if mtype and mtype.startswith("image"):
        return generate_hubspot_asset_url(path, profile=profile, base_path=base_path)

    path = obj.fragment and f"{path}#{obj.fragment}" or path
    path = obj.query and f"{path}?{obj.query}" or path

    return path  # , obj.query


def change_anchor_url_tag(asset_tag, profile: dict, base_path="/"):
    tag_name = asset_tag.name
    attr_name = "href"
    original_src = asset_tag.get(attr_name)

    if not original_src:
        return

    if original_src.startswith("http"):
        # 絶対パスは変換しない(外部の可能性)
        return

    new_src = change_anchor_url_rule(original_src, profile, base_path=base_path)

    asset_tag[attr_name] = new_src

    click.echo(f"href変更:  {tag_name}.{attr_name}: {original_src} -> {new_src}")


def extract_elements(soup: Soup, profile: dict, base_path="/"):
    """コンテンツを抜き出して(src)アセットURLの変換を行う
    - 不要な要素の削除(drops)
    """
    extract = profile.get("extract", None) or {}
    src = soup.select_one(extract["src"])

    drops = extract.get("drops", None) or []

    for i in drops:
        elm = src.select_one(i)
        elm and elm.extract()

    change_asset_url(src, profile, base_path=base_path)

    return src


def load_profile(profile):
    if not profile:
        return {}
    path = Path(profile)
    if not path.is_file or path.suffix != ".json":
        return {}

    profile_data = json.load(open(profile))
    return profile_data


@click.group()
@click.option("--profile", "-p", default=None)
@click.pass_context
def html(ctx, profile):
    ctx.obj["profile"] = load_profile(profile)
    pass


@html.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option("--output_file", "-o", type=click.Path(), default=None)
@click.pass_context
def asset_url(ctx, input_file, output_file):
    """
    HTMLファイル内の<img>タグのsrc属性のパスを一括置換するコマンドラインツール。

    INPUT_FILE: 読み込むHTMLファイルのパス。
    OUTPUT_FILE: 出力するHTMLファイルのパス。
    """
    if not output_file:
        path = Path(input_file)
        output_file = str(path.parent / f"out.{path.name}")

    try:
        click.echo(f'ファイル "{input_file}" を読み込んでいます...')
        with open(input_file, encoding="utf-8") as f:
            soup = Soup(f, "html.parser")

        change_asset_url(soup, profile=ctx.obj["profile"])

        click.echo(f'修正されたHTMLを "{output_file}" に書き込みます...')
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(str(soup))

        click.echo(f'処理が完了しました。修正されたHTMLは "{output_file}" に保存されました。')

    except Exception as e:
        click.echo(f"エラーが発生しました: {e}", err=True)


def update_css_url_paths(sheet, profile=None, base_path="/"):
    """CSSの url を 公開URLに変更"""
    # 2. 全てのルールとプロパティを走査し、url()を含むものを探す
    for rule in sheet:
        # StyleRule（セレクタを持つ通常のCSSルール）を対象とする
        if rule.type in [rule.STYLE_RULE, rule.FONT_FACE_RULE]:
            for property in rule.style:
                # プロパティの値に 'url(' が含まれているかチェック
                if "url(" in property.cssValue.cssText:
                    # cssutilsのValueオブジェクトを使って値を取得・操作
                    # url()関数を解析し、中のパス部分（URI）を変更する
                    new_values = []

                    for value in property.cssValue:
                        # Valueの種類がCSSFunction.URI_FUNCTION(url())であるかを確認
                        if value.type == "URI":  # CSSFunction.CSS_URI:
                            old_path = value.uri

                            new_path = generate_hubspot_asset_url(old_path, profile=profile, base_path=base_path)
                            # URIの値を新しいパスに変更
                            value.uri = new_path
                            new_values.append(value.cssText)
                        else:
                            # url()関数ではない他の値はそのまま維持
                            new_values.append(value.cssText)

                    # 変更後の値をプロパティに再設定
                    property.cssText = f"{property.name}: {' '.join(new_values)};"


@html.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option("--output_file", "-o", type=click.Path(), default=None)
@click.option("--base_path", "-b", default=None)
@click.pass_context
def css_url(ctx, input_file, output_file, base_path):
    """CSSSの url の内容を変更します"""
    base_path = base_path or "/"
    if not output_file:
        path = Path(input_file)
        output_file = str(path.parent / f"out.{path.name}")

    with open(input_file, encoding="utf-8") as f:
        sheet = cssutils.parseString(f.read())
        update_css_url_paths(sheet, profile=ctx.obj["profile"], base_path=base_path)

        with open(output_file, "w", encoding="utf-8") as f:
            # CSSの整形も自動で行われる (cssutils.CSSSerializer)
            f.write(sheet.cssText.decode("utf-8"))


@html.command()
@click.argument("directory", type=click.Path(exists=True))
@click.pass_context
def strip_qstr(ctx, directory):
    """
    指定されたディレクトリ内のファイル名からクエリ文字列を削除します。
    例: style.css?ver=6.7.3 -> style.css

    Args:
        directory (str): 処理対象のディレクトリパス
    """
    for root, _dirs, files in os.walk(directory):
        for filename in files:
            # 正規表現でファイル名にクエリ文字列が含まれているかチェック
            # 例: 'style.css?ver=6.7.3.css' を 'style.css.css' に
            # ※ wgetの保存方法によっては末尾に`.css`が追加される場合があるため、この例ではその可能性も考慮
            if "?" in filename:
                original_filepath = os.path.join(root, filename)
                # `?`以降の文字列を削除
                new_filename = re.sub(r"\?.*", "", filename)

                # wgetで保存されたファイルは、`.css?ver=6.7.3` のようなクエリ文字列がそのままファイル名に含まれるため、
                # 元の拡張子(`.css`や`.js`)が複数になることがある。
                # 例: `style.css?ver=6.7.3.css` -> `style.css.css`
                # このようなファイル名の場合は、最後の`.css`のみを残すように修正
                if new_filename.endswith(".css.css"):
                    new_filename = new_filename.replace(".css.css", ".css")
                elif new_filename.endswith(".js.js"):
                    new_filename = new_filename.replace(".js.js", ".js")

                new_filepath = os.path.join(root, new_filename)

                # ファイル名を変更
                try:
                    os.rename(original_filepath, new_filepath)
                    print(f"Renamed: {original_filepath} -> {new_filepath}")
                except OSError as e:
                    print(f"Error renaming {original_filepath}: {e}")


@html.command()
@click.argument("src")
@click.pass_context
def hs_url(ctx, src):
    """アセットURLを生成"""
    THEME = os.environ["HUBSPOT_FOLDER"]
    dst = f"{{{{ get_asset_url('/{THEME}/{src}') }}}}"
    print(dst)


@html.command()
@click.argument("src_path")
@click.option("--output_file", "-o", type=click.Path(), default=None)
@click.option("--base_path", "-b", default="/")
@click.pass_context
def extract(ctx, src_path, output_file, base_path):
    """コンテンツ抜き出し"""

    src = Path(src_path)
    if not src.is_file or src.suffix != ".html":
        print("source error")
        return

    profile_data = ctx.obj["profile"]

    if not output_file:
        path = Path(src_path)
        output_file = str(path.parent / f"out.{path.name}")

    with open(src_path, encoding="utf-8") as f:
        soup = Soup(f, "html.parser")
        res = extract_elements(soup, profile_data, base_path=base_path)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(str(res))


def generate_toc(soup, title="目次"):
    heading_tags = ["h2", "h3", "h4", "h5"]
    headings = soup.find_all(heading_tags)

    if not headings:
        return str(soup)

    # 2. ナビゲーションのルートを作成
    nav_tag = soup.new_tag("nav", **{"class": "toc"})
    root_ul = soup.new_tag("ul")
    nav_tag.append(root_ul)

    # 階層管理用のスタック (現在のレベル, 現在のul要素)
    # h2をレベル2として、初期状態をセット
    stack = [(1, root_ul)]

    for i, header in enumerate(headings):
        # 見出しのレベルを取得 (h2 -> 2, h3 -> 3...)
        level = int(header.name[1])

        # アンカー用のID設定 (IDがない場合は自動生成)
        if not header.get("id"):
            header["id"] = f"section-{i}"
        header_id = header["id"]
        header_text = header.get_text()

        # 3. 適切な階層までスタックを戻す
        # 今のレベルより浅い（数字が小さい）レベルが来たらスタックから取り出す
        while stack and stack[-1][0] >= level:
            stack.pop()

        # 現在の親ULを取得
        parent_ul = stack[-1][1]

        # 4. 新しいリストアイテム (li > a) の作成
        new_li = soup.new_tag("li")
        new_a = soup.new_tag("a", href=f"#{header_id}")
        new_a.string = header_text
        new_li.append(new_a)
        parent_ul.append(new_li)

        # 5. 次の要素が子階層になる可能性に備え、新しいULを準備
        new_ul = soup.new_tag("ul")
        new_li.append(new_ul)
        stack.append((level, new_ul))

    # 不要な空のULを削除するクリーンアップ
    for ul in nav_tag.find_all("ul"):
        if not ul.contents:
            ul.decompose()

    container_div = soup.new_tag("div", attrs={"class": "toc-container"})
    title_div = soup.new_tag("div", attrs={"class": "toc-title"})
    title_p = soup.new_tag("p")
    title_p.string = title
    title_div.append(title_p)

    container_div.append(title_div)
    container_div.append(nav_tag)

    # 先頭にnavを挿入（例としてbodyの先頭）
    if soup.body:
        soup.body.insert(0, container_div)
    else:
        # bodyがない場合は全体の先頭に
        soup.insert(0, container_div)

    return soup


@html.command()
@click.argument("src_path")
@click.option("--output_file", "-o", type=click.Path(), default=None)
@click.pass_context
def make_nav(ctx, src_path, output_file):
    """ページ内ナビゲーションを作る"""

    if src_path == "-":
        content = sys.stdin.read()
        if not content:
            print("データがありません")
            return
        soup = Soup(content, "html.parser")

    else:
        with open(src_path, encoding="utf-8") as f:
            soup = Soup(f, "html.parser")

    if soup:
        res = generate_toc(soup)
        print(res.prettify())
