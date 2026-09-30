"""
BBS (Bulletin Board System) models for Evennia MUD.
"""

from django.db import models
from django.db.models import Max
from evennia.accounts.models import AccountDB


class Board(models.Model):
    """
    A bulletin board that contains posts.
    """
    
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Unique name of the board"
    )
    description = models.TextField(
        help_text="Description of what this board is for"
    )
    read_perm = models.CharField(
        max_length=100,
        blank=True,
        help_text="Permission required to read this board (blank = everyone)"
    )
    write_perm = models.CharField(
        max_length=100,
        blank=True,
        help_text="Permission required to post to this board (blank = everyone)"
    )
    is_ic = models.BooleanField(
        default=False,
        help_text="Is this an in-character board?"
    )
    allow_anonymous = models.BooleanField(
        default=False,
        help_text="Allow anonymous posts on this board?"
    )
    required_flags = models.CharField(
        max_length=200,
        blank=True,
        help_text="Comma-separated list of required character flags to see/use this board"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        app_label = 'bbs'
        ordering = ['name']
        verbose_name = 'Board'
        verbose_name_plural = 'Boards'
    
    def __str__(self):
        return self.name
    
    def get_required_flags_list(self):
        """Return list of required flags."""
        if not self.required_flags:
            return []
        return [flag.strip() for flag in self.required_flags.split(',') if flag.strip()]


class Post(models.Model):
    """
    A post on a bulletin board.
    """
    
    author = models.ForeignKey(
        AccountDB,
        on_delete=models.CASCADE,
        related_name='bbs_posts',
        help_text="Account that created this post"
    )
    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name='posts',
        help_text="Board this post belongs to"
    )
    title = models.CharField(
        max_length=200,
        help_text="Title of the post"
    )
    body = models.TextField(
        help_text="Content of the post"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sequence_number = models.IntegerField(
        help_text="Auto-incrementing post number per board"
    )
    read_perm = models.CharField(
        max_length=100,
        blank=True,
        help_text="Permission required to read this post (blank = inherit from board)"
    )
    write_perm = models.CharField(
        max_length=100,
        blank=True,
        help_text="Permission required to comment on this post (blank = inherit from board)"
    )
    is_anonymous = models.BooleanField(
        default=False,
        help_text="Is this post anonymous?"
    )
    revealed_by = models.ManyToManyField(
        AccountDB,
        related_name='revealed_posts',
        blank=True,
        help_text="Accounts that can see the author of this anonymous post"
    )
    
    class Meta:
        app_label = 'bbs'
        ordering = ['board', 'sequence_number']
        unique_together = [['board', 'sequence_number']]
        verbose_name = 'Post'
        verbose_name_plural = 'Posts'
    
    def __str__(self):
        return f"{self.board.name}/{self.sequence_number}: {self.title}"
    
    def save(self, *args, **kwargs):
        """Auto-increment sequence_number per board."""
        if not self.pk and not self.sequence_number:
            # Get the highest sequence number for this board
            max_seq = Post.objects.filter(board=self.board).aggregate(
                Max('sequence_number')
            )['sequence_number__max']
            self.sequence_number = (max_seq or 0) + 1
        super().save(*args, **kwargs)
    
    def get_author_name(self, viewer=None):
        """
        Get the author name, accounting for anonymity.
        
        Args:
            viewer: AccountDB object of the viewer (optional)
        
        Returns:
            str: Author name or "Anonymous"
        """
        if not self.is_anonymous:
            return self.author.username
        
        # Check if viewer can see the real author
        if viewer and (
            viewer == self.author or
            viewer.check_permstring("Admin") or
            viewer in self.revealed_by.all()
        ):
            return f"{self.author.username} (anonymous)"
        
        return "Anonymous"


class Comment(models.Model):
    """
    A comment on a bulletin board post.
    """
    
    author = models.ForeignKey(
        AccountDB,
        on_delete=models.CASCADE,
        related_name='bbs_comments',
        help_text="Account that created this comment"
    )
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name='comments',
        help_text="Post this comment belongs to"
    )
    body = models.TextField(
        help_text="Content of the comment"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    read_perm = models.CharField(
        max_length=100,
        blank=True,
        help_text="Permission required to read this comment (blank = inherit from post)"
    )
    write_perm = models.CharField(
        max_length=100,
        blank=True,
        help_text="Permission required to reply to this comment (blank = inherit from post)"
    )
    
    class Meta:
        app_label = 'bbs'
        ordering = ['created_at']
        verbose_name = 'Comment'
        verbose_name_plural = 'Comments'
    
    def __str__(self):
        return f"Comment by {self.author.username} on {self.post}"
