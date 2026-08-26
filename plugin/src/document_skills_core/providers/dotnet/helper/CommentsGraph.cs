// Strict one-level threaded-comment graph projection.

using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;
using W15 = DocumentFormat.OpenXml.Office2013.Word;

internal static class CommentsGraph
{
    internal static List<CommentNode> BuildNodes(
        WordprocessingDocument document,
        int maximum)
    {
        var mainPart = document.MainDocumentPart;
        var commentsPart = mainPart?.WordprocessingCommentsPart;
        if (mainPart is null || commentsPart?.Comments is null)
        {
            return new List<CommentNode>();
        }
        var anchors = BuildParagraphAnchors(mainPart);
        var comments = commentsPart.Comments.Elements<Comment>()
            .Take(maximum)
            .ToList();
        var nodes = new List<CommentNode>();
        var byId = new Dictionary<string, CommentNode>(StringComparer.Ordinal);
        var byParagraphId = new Dictionary<string, CommentNode>(StringComparer.Ordinal);
        var extensions = ReadExtensions(mainPart.WordprocessingCommentsExPart);
        foreach (var comment in comments)
        {
            var id = comment.Id?.Value ?? "";
            CommentsInfrastructure.ValidateCommentId(id);
            if (byId.ContainsKey(id))
            {
                throw new InvalidOperationException("DOCX contains duplicate comment ids.");
            }
            var paragraphs = comment.Elements<Paragraph>().ToList();
            var paragraphId = paragraphs.Count == 1
                ? paragraphs[0].ParagraphId?.Value
                : null;
            var extension = paragraphId is not null
                && extensions.TryGetValue(paragraphId, out var found)
                ? found
                : null;
            var node = new CommentNode(
                comment,
                id,
                paragraphId,
                extension,
                anchors.GetValueOrDefault(id));
            nodes.Add(node);
            byId.Add(id, node);
            if (paragraphId is not null && !byParagraphId.TryAdd(paragraphId, node))
            {
                throw new InvalidOperationException(
                    "DOCX contains duplicate comment paragraph ids.");
            }
        }
        foreach (var node in nodes)
        {
            var parentParagraphId = node.Extension?.ParaIdParent?.Value;
            if (parentParagraphId is null)
            {
                node.ThreadId = node.Id;
                node.Resolved = node.Extension?.Done?.Value ?? false;
                continue;
            }
            if (!byParagraphId.TryGetValue(parentParagraphId, out var parent))
            {
                throw new InvalidOperationException(
                    "DOCX contains a dangling comment reply parent.");
            }
            node.ParentId = parent.Id;
        }
        foreach (var node in nodes.Where(item => item.ParentId is not null))
        {
            var parent = byId[node.ParentId!];
            if (parent.ParentId is not null || node.Extension?.Done?.Value is true)
            {
                throw new InvalidOperationException(
                    "DOCX contains a nested or independently resolved reply.");
            }
            node.ThreadId = parent.Id;
            node.Resolved = parent.Resolved;
            node.Anchor ??= parent.Anchor;
        }
        var ordered = new List<CommentNode>();
        foreach (var root in nodes.Where(item => item.ParentId is null))
        {
            ordered.Add(root);
            ordered.AddRange(nodes.Where(item => item.ParentId == root.Id));
        }
        if (ordered.Count != nodes.Count)
        {
            throw new InvalidOperationException("DOCX contains an invalid comment graph.");
        }
        return ordered;
    }

    internal static object ProjectNode(CommentNode node) => new
    {
        id = node.Id,
        parent_comment_id = node.ParentId,
        thread_id = node.ThreadId,
        resolved = node.Resolved,
        author = node.Comment.Author?.Value ?? "",
        date = FormatDate(node.Comment.Date),
        text = string.Concat(node.Comment.Descendants<Text>().Select(item => item.Text)),
        anchor = node.Anchor is null
            ? null
            : new
            {
                story = "body",
                paragraph_index = node.Anchor.ParagraphIndex,
                range = "paragraph",
            },
    };

    private static Dictionary<string, W15.CommentEx> ReadExtensions(
        WordprocessingCommentsExPart? part)
    {
        var result = new Dictionary<string, W15.CommentEx>(StringComparer.Ordinal);
        if (part?.CommentsEx is null) return result;
        foreach (var extension in part.CommentsEx.Elements<W15.CommentEx>())
        {
            var paragraphId = extension.ParaId?.Value
                ?? throw new InvalidOperationException(
                    "DOCX contains a comment extension without a paragraph id.");
            if (!result.TryAdd(paragraphId, extension))
            {
                throw new InvalidOperationException(
                    "DOCX contains duplicate comment extension ids.");
            }
        }
        return result;
    }

    private static Dictionary<string, CommentAnchor> BuildParagraphAnchors(
        MainDocumentPart mainPart)
    {
        var anchors = new Dictionary<string, CommentAnchor>(StringComparer.Ordinal);
        var paragraphs = mainPart.Document.Body?.Descendants<Paragraph>().ToList()
            ?? new List<Paragraph>();
        for (var index = 0; index < paragraphs.Count; index++)
        {
            var starts = paragraphs[index].Descendants<CommentRangeStart>()
                .Select(item => item.Id?.Value ?? "")
                .Where(id => id.Length > 0)
                .ToHashSet(StringComparer.Ordinal);
            var ends = paragraphs[index].Descendants<CommentRangeEnd>()
                .Select(item => item.Id?.Value ?? "")
                .Where(id => id.Length > 0)
                .ToHashSet(StringComparer.Ordinal);
            foreach (var id in starts.Intersect(ends))
            {
                if (!anchors.TryAdd(id, new CommentAnchor(paragraphs[index], index)))
                {
                    throw new InvalidOperationException(
                        "DOCX contains an ambiguous comment anchor.");
                }
            }
        }
        return anchors;
    }

    private static string FormatDate(DateTimeValue? value) => value?.Value is DateTime date
        ? date.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        : "";
}

internal sealed class CommentNode
{
    internal CommentNode(
        Comment comment,
        string id,
        string? paragraphId,
        W15.CommentEx? extension,
        CommentAnchor? anchor)
    {
        Comment = comment;
        Id = id;
        ParagraphId = paragraphId;
        Extension = extension;
        Anchor = anchor;
    }

    internal Comment Comment { get; }
    internal string Id { get; }
    internal string? ParagraphId { get; }
    internal W15.CommentEx? Extension { get; }
    internal CommentAnchor? Anchor { get; set; }
    internal string? ParentId { get; set; }
    internal string ThreadId { get; set; } = "";
    internal bool Resolved { get; set; }
    internal string Author => Comment.Author?.Value ?? "";
}

internal sealed record CommentAnchor(Paragraph Paragraph, int ParagraphIndex);
