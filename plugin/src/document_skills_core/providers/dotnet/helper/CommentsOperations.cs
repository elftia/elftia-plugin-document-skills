// Bounded threaded-comment operations for the private OpenXML helper.

using System.Text.Json;
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;
using W15 = DocumentFormat.OpenXml.Office2013.Word;

internal static class CommentsOperations
{
    internal static object Read(JsonElement request)
    {
        var inputPath = request.GetProperty("input_path").GetString()!;
        var maxComments = request.TryGetProperty("max_comments", out var maximum)
            && maximum.TryGetInt32(out var requestedMaximum)
            ? Math.Clamp(requestedMaximum, 1, 10_001)
            : 10_000;
        using var document = WordprocessingDocument.Open(inputPath, false);
        var nodes = CommentsGraph.BuildNodes(document, maxComments);
        var filterId = request.TryGetProperty("filter_id", out var idFilter)
            ? idFilter.GetString()
            : null;
        var filterAuthor = request.TryGetProperty("filter_author", out var authorFilter)
            ? authorFilter.GetString()
            : null;
        var comments = nodes
            .Where(node => filterId is null || node.Id == filterId)
            .Where(node => filterAuthor is null || node.Author == filterAuthor)
            .Take(maxComments)
            .Select(CommentsGraph.ProjectNode)
            .ToList();
        return new { comments };
    }

    internal static object Add(JsonElement request)
    {
        var inputPath = request.GetProperty("input_path").GetString()!;
        var outputPath = request.GetProperty("output_path").GetString()!;
        var payload = request.GetProperty("comment");
        var text = payload.GetProperty("text").GetString()!;
        var author = payload.GetProperty("author").GetString() ?? "";
        CommentsInfrastructure.RejectActiveText(text);
        var hasAnchor = payload.TryGetProperty("anchor", out var anchor)
            && anchor.ValueKind == JsonValueKind.Object;
        var hasParent = payload.TryGetProperty("parent_comment_id", out var parentValue)
            && parentValue.ValueKind == JsonValueKind.String;
        if (hasAnchor == hasParent)
        {
            throw new InvalidOperationException(
                "Comment add requires exactly one anchor or parent comment id.");
        }

        File.Copy(inputPath, outputPath, overwrite: true);
        using var document = WordprocessingDocument.Open(outputPath, true);
        var mainPart = document.MainDocumentPart
            ?? throw new InvalidOperationException("DOCX has no main document part.");
        var commentsPart = CommentsInfrastructure.EnsureCommentsPart(mainPart);
        var commentId = CommentsInfrastructure.NextCommentId(commentsPart);
        var paragraphId = CommentsInfrastructure.GenerateParagraphId(
            mainPart,
            commentsPart,
            commentId);
        var commentParagraph = new Paragraph { ParagraphId = paragraphId };
        commentParagraph.AppendChild(
            new Run(new Text(text) { Space = SpaceProcessingModeValues.Preserve }));
        var comment = new Comment
        {
            Id = commentId,
            Author = author,
            Date = DateTime.UtcNow,
        };
        comment.AppendChild(commentParagraph);

        var commentsExPart = CommentsInfrastructure.EnsureCommentsExPart(mainPart);
        if (hasAnchor)
        {
            var target = CommentsInfrastructure.ResolveRequestedAnchor(mainPart, anchor);
            commentsPart.Comments.AppendChild(comment);
            commentsExPart.CommentsEx.AppendChild(
                new W15.CommentEx { ParaId = paragraphId, Done = false });
            CommentsInfrastructure.AppendRangeMarkers(target, commentId);
        }
        else
        {
            AddReply(
                mainPart,
                commentsPart,
                commentsExPart,
                comment,
                paragraphId,
                parentValue.GetString()!);
        }

        commentsPart.Comments.Save();
        commentsExPart.CommentsEx.Save();
        mainPart.Document.Save();
        return new { comment_id = commentId };
    }

    internal static object Resolve(JsonElement request)
    {
        var inputPath = request.GetProperty("input_path").GetString()!;
        var outputPath = request.GetProperty("output_path").GetString()!;
        var commentId = request.GetProperty("comment_id").GetString()!;
        var resolved = request.GetProperty("resolved").GetBoolean();
        CommentsInfrastructure.ValidateCommentId(commentId);

        File.Copy(inputPath, outputPath, overwrite: true);
        using var document = WordprocessingDocument.Open(outputPath, true);
        var mainPart = document.MainDocumentPart
            ?? throw new InvalidOperationException("DOCX has no main document part.");
        var commentsPart = mainPart.WordprocessingCommentsPart
            ?? throw new InvalidOperationException("DOCX has no comments part.");
        var comment = CommentsInfrastructure.FindComment(commentsPart, commentId);
        var paragraphId = CommentsInfrastructure.EnsureSingleParagraphId(
            mainPart,
            commentsPart,
            comment,
            commentId);
        var commentsExPart = CommentsInfrastructure.EnsureCommentsExPart(mainPart);
        var extension = CommentsInfrastructure.EnsureRootExtension(
            commentsExPart,
            paragraphId);
        extension.Done = resolved;
        commentsPart.Comments.Save();
        commentsExPart.CommentsEx.Save();
        return new { comment_id = commentId, resolved };
    }

    private static void AddReply(
        MainDocumentPart mainPart,
        WordprocessingCommentsPart commentsPart,
        WordprocessingCommentsExPart commentsExPart,
        Comment comment,
        string paragraphId,
        string parentId)
    {
        CommentsInfrastructure.ValidateCommentId(parentId);
        var parent = CommentsInfrastructure.FindComment(commentsPart, parentId);
        var parentParagraphId = CommentsInfrastructure.EnsureSingleParagraphId(
            mainPart,
            commentsPart,
            parent,
            parentId);
        var parentExtension = CommentsInfrastructure.EnsureRootExtension(
            commentsExPart,
            parentParagraphId);
        if (parentExtension.Done?.Value is true)
        {
            throw new InvalidOperationException(
                "Replies cannot be added to a resolved comment thread.");
        }
        var target = CommentsInfrastructure.ResolveExistingAnchor(mainPart, parentId);
        commentsPart.Comments.AppendChild(comment);
        commentsExPart.CommentsEx.AppendChild(
            new W15.CommentEx
            {
                ParaId = paragraphId,
                ParaIdParent = parentParagraphId,
                Done = false,
            });
        CommentsInfrastructure.AppendRangeMarkers(target, comment.Id!.Value!);
    }
}
