// Typed OpenXML helpers for bounded threaded-comment mutations.

using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;
using W15 = DocumentFormat.OpenXml.Office2013.Word;

internal static class CommentsInfrastructure
{
    internal static CommentAnchor ResolveRequestedAnchor(
        MainDocumentPart mainPart,
        System.Text.Json.JsonElement anchor)
    {
        if (anchor.GetProperty("story").GetString() != "body"
            || anchor.GetProperty("range").GetString() != "paragraph")
        {
            throw new InvalidOperationException("Unsupported comment anchor.");
        }
        var paragraphIndex = anchor.GetProperty("paragraph_index").GetInt32();
        var expectedText = anchor.GetProperty("expected_text").GetString() ?? "";
        var paragraphs = mainPart.Document.Body?.Descendants<Paragraph>().ToList()
            ?? new List<Paragraph>();
        if (paragraphIndex < 0 || paragraphIndex >= paragraphs.Count)
        {
            throw new InvalidOperationException(
                "Comment anchor paragraph does not exist.");
        }
        var paragraph = paragraphs[paragraphIndex];
        var actualText = string.Concat(
            paragraph.Descendants<Text>().Select(item => item.Text));
        if (actualText != expectedText)
        {
            throw new InvalidOperationException(
                "Comment anchor text precondition did not match.");
        }
        return new CommentAnchor(paragraph, paragraphIndex);
    }

    internal static CommentAnchor ResolveExistingAnchor(
        MainDocumentPart mainPart,
        string commentId)
    {
        var starts = mainPart.Document.Descendants<CommentRangeStart>()
            .Where(item => item.Id?.Value == commentId)
            .ToList();
        var ends = mainPart.Document.Descendants<CommentRangeEnd>()
            .Where(item => item.Id?.Value == commentId)
            .ToList();
        var references = mainPart.Document.Descendants<CommentReference>()
            .Where(item => item.Id?.Value == commentId)
            .ToList();
        if (starts.Count != 1 || ends.Count != 1 || references.Count != 1)
        {
            throw new InvalidOperationException(
                "Parent comment does not have one supported anchor.");
        }
        var paragraph = starts[0].Ancestors<Paragraph>().FirstOrDefault();
        if (paragraph is null
            || ends[0].Ancestors<Paragraph>().FirstOrDefault() != paragraph
            || references[0].Ancestors<Paragraph>().FirstOrDefault() != paragraph)
        {
            throw new InvalidOperationException(
                "Parent comment anchor crosses an unsupported boundary.");
        }
        var paragraphs = mainPart.Document.Body?.Descendants<Paragraph>().ToList()
            ?? new List<Paragraph>();
        var paragraphIndex = paragraphs.IndexOf(paragraph);
        if (paragraphIndex < 0)
        {
            throw new InvalidOperationException("Parent comment is outside the body.");
        }
        return new CommentAnchor(paragraph, paragraphIndex);
    }

    internal static void AppendRangeMarkers(CommentAnchor anchor, string commentId)
    {
        var rangeStart = new CommentRangeStart { Id = commentId };
        var rangeEnd = new CommentRangeEnd { Id = commentId };
        var reference = new Run(new CommentReference { Id = commentId });
        var firstContent = anchor.Paragraph.ChildElements.FirstOrDefault(
            element => element is not ParagraphProperties
                && element is not CommentRangeStart);
        if (firstContent is null)
        {
            anchor.Paragraph.AppendChild(rangeStart);
        }
        else
        {
            anchor.Paragraph.InsertBefore(rangeStart, firstContent);
        }
        anchor.Paragraph.Append(rangeEnd, reference);
    }

    internal static WordprocessingCommentsPart EnsureCommentsPart(
        MainDocumentPart mainPart)
    {
        var part = mainPart.WordprocessingCommentsPart
            ?? mainPart.AddNewPart<WordprocessingCommentsPart>();
        part.Comments ??= new Comments();
        EnsureCommentNamespaces(part.Comments);
        return part;
    }

    internal static WordprocessingCommentsExPart EnsureCommentsExPart(
        MainDocumentPart mainPart)
    {
        var part = mainPart.WordprocessingCommentsExPart
            ?? mainPart.AddNewPart<WordprocessingCommentsExPart>();
        part.CommentsEx ??= new W15.CommentsEx();
        return part;
    }

    internal static W15.CommentEx EnsureRootExtension(
        WordprocessingCommentsExPart part,
        string paragraphId)
    {
        var matches = part.CommentsEx.Elements<W15.CommentEx>()
            .Where(item => item.ParaId?.Value == paragraphId)
            .ToList();
        if (matches.Count > 1)
        {
            throw new InvalidOperationException(
                "DOCX contains duplicate comment extension ids.");
        }
        var extension = matches.SingleOrDefault();
        if (extension is null)
        {
            extension = new W15.CommentEx { ParaId = paragraphId, Done = false };
            part.CommentsEx.AppendChild(extension);
        }
        if (extension.ParaIdParent?.Value is not null)
        {
            throw new InvalidOperationException(
                "Reply comments cannot be used as thread roots.");
        }
        return extension;
    }

    internal static Comment FindComment(
        WordprocessingCommentsPart part,
        string commentId)
    {
        var matches = part.Comments.Elements<Comment>()
            .Where(item => item.Id?.Value == commentId)
            .ToList();
        if (matches.Count != 1)
        {
            throw new InvalidOperationException(
                "Requested comment id does not identify one comment.");
        }
        return matches[0];
    }

    internal static string EnsureSingleParagraphId(
        MainDocumentPart mainPart,
        WordprocessingCommentsPart commentsPart,
        Comment comment,
        string commentId)
    {
        EnsureCommentNamespaces(commentsPart.Comments);
        var paragraphs = comment.Elements<Paragraph>().ToList();
        if (paragraphs.Count != 1)
        {
            throw new InvalidOperationException(
                "Thread operations require a single-paragraph comment.");
        }
        var paragraphId = paragraphs[0].ParagraphId?.Value;
        if (paragraphId is null)
        {
            paragraphId = GenerateParagraphId(
                mainPart,
                commentsPart,
                commentId);
            paragraphs[0].ParagraphId = paragraphId;
        }
        return paragraphId;
    }

    internal static string GenerateParagraphId(
        MainDocumentPart mainPart,
        WordprocessingCommentsPart commentsPart,
        string commentId)
    {
        var used = mainPart.Document.Descendants<Paragraph>()
            .Select(item => item.ParagraphId?.Value)
            .Concat(commentsPart.Comments.Descendants<Paragraph>()
                .Select(item => item.ParagraphId?.Value))
            .Where(value => value is not null)
            .Cast<string>()
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        for (var seed = 0; seed <= 10_000; seed++)
        {
            var input = Encoding.UTF8.GetBytes(
                $"elftia-comment-{commentId}-{seed.ToString(CultureInfo.InvariantCulture)}");
            var candidate = Convert.ToHexString(SHA256.HashData(input).AsSpan(0, 4));
            if (used.Add(candidate)) return candidate;
        }
        throw new InvalidOperationException("Could not allocate a comment paragraph id.");
    }

    internal static string NextCommentId(WordprocessingCommentsPart part)
    {
        var maximum = -1;
        foreach (var comment in part.Comments.Elements<Comment>())
        {
            var id = comment.Id?.Value ?? "";
            ValidateCommentId(id);
            maximum = Math.Max(maximum, int.Parse(id, CultureInfo.InvariantCulture));
        }
        if (maximum == int.MaxValue)
        {
            throw new InvalidOperationException("Comment id space is exhausted.");
        }
        return (maximum + 1).ToString(CultureInfo.InvariantCulture);
    }

    internal static void ValidateCommentId(string value)
    {
        if (!int.TryParse(
                value,
                NumberStyles.None,
                CultureInfo.InvariantCulture,
                out var parsed)
            || parsed < 0)
        {
            throw new InvalidOperationException("DOCX contains an invalid comment id.");
        }
    }

    internal static void RejectActiveText(string text)
    {
        var lowered = text.ToLowerInvariant();
        var forbidden = new[]
        {
            "http://", "https://", "www.", "javascript:", "file://",
            "<script", "<a ", "href=", "vbscript:",
        };
        if (forbidden.Any(lowered.Contains))
        {
            throw new InvalidOperationException(
                "Comment text contains forbidden active content.");
        }
    }

    private static void EnsureCommentNamespaces(Comments comments)
    {
        EnsureNamespace(
            comments,
            "mc",
            "http://schemas.openxmlformats.org/markup-compatibility/2006");
        EnsureNamespace(
            comments,
            "w14",
            "http://schemas.microsoft.com/office/word/2010/wordml");
        var existing = comments.MCAttributes?.Ignorable?.Value ?? "";
        var tokens = existing.Split(
                ' ',
                StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .ToList();
        if (!tokens.Contains("w14", StringComparer.Ordinal)) tokens.Add("w14");
        comments.MCAttributes ??= new MarkupCompatibilityAttributes();
        comments.MCAttributes.Ignorable = string.Join(" ", tokens);
    }

    private static void EnsureNamespace(
        OpenXmlElement root,
        string prefix,
        string namespaceUri)
    {
        var existing = root.NamespaceDeclarations
            .Where(item => item.Key == prefix)
            .Select(item => item.Value)
            .SingleOrDefault();
        if (existing is null)
        {
            root.AddNamespaceDeclaration(prefix, namespaceUri);
        }
        else if (existing != namespaceUri)
        {
            throw new InvalidOperationException(
                "DOCX contains a conflicting comment namespace declaration.");
        }
    }
}
